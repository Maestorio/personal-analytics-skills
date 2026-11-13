#!/usr/bin/env python3
"""
assemble_artifact.py — deterministic validation helpers for save-to-library.

Commands:
  validate-stress             Validate portfolio stress-test YAML (schema v2 only, E3 logic)
  validate-forecast           Validate forecast .md frontmatter (B3 + B4.1a logic)
  validate-audit              Validate audit source frontmatter (A2 logic)
  validate-retro-audit-paths  Pre-emit guard for Workflow D (atomic retro-audit save)
  determine-subfolder         Determine audit subfolder from trust subdomains (A3 logic)
  compute-inclusion           Check auto-inclusion: pin OR any trust=HIGH (A4 logic)
  validate-monitor-report     Workflow L3: monitor-report fields + ready /command in suggested_action;
                              --root R — каждый пункт monitoring[] активных прогнозов/сценариев с прошедшей
                              датой отражён алертом с monitoring_id или строкой monitoring_checked (FM-20)
  validate-decision           decision@1 (schema.md §3.1) — обёртка над ds_schemas.validate_decision
  validate-report             шапка отчёта report@1 (schema.md §4.3) и её блок decisions: — Workflow N2
  stamp-report --root R --doc Portfolio/reports/<файл>.md
                              ставит в шапку сохранённого отчёта recorded_at (time_msk.now_iso) и
                              schema_version: report@1, если их нет; повтор ничего не меняет — Workflow N2
  stamp-report --root R --doc Portfolio/weekly-reviews/weekly-review-<stock|bond>-<дата>.yaml
                              обзор недели (R28): recorded_at, если нет, и verification_priority каждой бумаги
                              функцией движка (решения, условия, гейт модуля (б)); вывод — «тикер: было → стало»
                              — Workflow F3

Input: JSON via stdin, или --file <артефакт> (обзор недели: + --root <корень Claude-Memory> — контекст
       verification_priority из последних решений и действующих условий, только чтение)
Output: JSON to stdout
Exit 0 always (caller checks result["valid"] / result["blocking_count"]).
Exit 1 on bad command or JSON parse error.
"""

import sys
import json
import re
import calendar
import os
from datetime import date

# Кодлисты (`codelists.json`, загрузчик `codelists.py`) — канон в _shared-references/; в упакованном
# .skill — в своей scripts/ (pack.sh кладёт оба файла). Как у constraint_engine: сначала каталог скрипта.
_CL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cl_cand in (_CL_HERE, os.path.normpath(os.path.join(_CL_HERE, "..", "..", "..", "_shared-references"))):
    if _cl_cand not in sys.path:
        sys.path.insert(0, _cl_cand)
import codelists  # noqa: E402
import hub_settings  # noqa: E402
import rating_check as _rating_check  # noqa: E402
import macro_grid_check as _macro_grid_check  # noqa: E402


# ---------------------------------------------------------------------------
# YAML duplicate-key guard (stdlib-only)
# ---------------------------------------------------------------------------
#
# YAML спецификация запрещает дублирование mapping-ключей на одном уровне,
# но PyYAML/`yaml.safe_load` молча перетирает старое значение, а js-yaml
# (viewer) кидает исключение и весь файл не рендерится. Этот guard ловит
# проблему ДО записи в Claude-Memory, чтобы виноватый артефакт не попал
# в библиотеку.
#
# Два слоя (STL-6, 2026-08-03):
#   • find_yaml_top_level_duplicates — исторический top-level guard
#     («HST Tier 2 patch добавил второй monitoring: после FCA»);
#   • find_yaml_nested_duplicates — indentation-aware сканер дублей на ЛЮБОМ
#     уровне вложенности. Прецедент: weekly-review-stock-2026-06-28 нёс три
#     вложенных дубля unconstrained_verdict (стрэй-копия после user_constraints
#     при ручной правке) — PyYAML молча дедупил, js-yaml во вьюере падал,
#     top-level guard не видел. Сканер stdlib-only; зеркало для тестов —
#     yaml.compose-walk (если PyYAML доступен).

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:(\s|$)")
# Индикаторы chomping/indent в любом порядке: |-, |2, |2-, |-2, >+ … (аудит FP-4)
_BLOCK_SCALAR_TAIL_RE = re.compile(r":\s*[|>][0-9+\-]*\s*(#.*)?$")


def find_yaml_top_level_duplicates(text: str) -> list:
    """Возвращает список словарей про top-level дубликаты YAML-ключей.

    {key, first_line, duplicate_line} — 1-indexed line numbers.

    Игнорирует комментарии, пустые строки, list-items (`-`), отступлённые
    линии и тело multi-line block scalars (`|`/`>`).
    """
    if not isinstance(text, str):
        return []

    seen: dict[str, int] = {}
    duplicates: list[dict] = []
    in_block_scalar = False
    block_scalar_indent: int | None = None  # None = «ещё не зафиксирован»

    for lineno, line in enumerate(text.splitlines(), start=1):
        if in_block_scalar:
            if not line.strip():
                continue
            stripped = line.lstrip(" \t")
            indent = len(line) - len(stripped)
            if block_scalar_indent is None:
                # Первая непустая строка определяет отступ блока.
                if indent == 0:
                    in_block_scalar = False
                    block_scalar_indent = None
                    # fall through — обработать как обычную строку
                else:
                    block_scalar_indent = indent
                    continue
            else:
                if indent < block_scalar_indent:
                    in_block_scalar = False
                    block_scalar_indent = None
                    # fall through
                else:
                    continue

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("---", "..."):
            seen = {}  # новый YAML-документ — свой namespace ключей (аудит FP-3)
            continue
        if line[:1] in (" ", "\t", "-"):
            continue

        m = _TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1)

        if _BLOCK_SCALAR_TAIL_RE.search(line):
            in_block_scalar = True
            block_scalar_indent = None

        if key in seen:
            duplicates.append({
                "key": key,
                "first_line": seen[key],
                "duplicate_line": lineno,
            })
        else:
            seen[key] = lineno

    return duplicates


# Ключ mapping-строки: plain-токен (без ':' и '#'), либо в кавычках
# ("2026-12-31": — реальный кейс values-блоков FCA). Колонка после ключа
# обязана сопровождаться пробелом/EOL, чтобы не срабатывать на URL (https://…).
_NESTED_KEY_RE = re.compile(
    r'^("(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<plain>[^\s#\'"\-\[{][^:#]*?))\s*:(?=\s|$)'
)
_STRICT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")

# Индикаторы block scalar в любом порядке (|2-, |-2, >+, |2 …) — аудит 2026-08-03 FP-4.
_BLOCK_INDICATOR_ONLY_RE = re.compile(r"^[|>][0-9+\-]*\s*(#.*)?$")

# Символы, ПОСЛЕ которых кавычка открывает строку. Апостроф внутри слова
# (Ivan's) кавычкой не считается — аудит 2026-08-03 (fake-flow разоружал сканер).
_QUOTE_GATE = " \t[{,:"

_DQ_CLOSED_RE = re.compile(r'^"(?:[^"\\]|\\.)*"')
_SQ_CLOSED_RE = re.compile(r"^'(?:[^']|'')*'(?!')")


def _quoted_scalar_open(vstrip: str) -> str | None:
    """Значение начинается кавычкой и НЕ закрывается на этой строке →
    вернуть символ кавычки (многострочный quoted-скаляр), иначе None."""
    if vstrip.startswith('"'):
        return None if _DQ_CLOSED_RE.match(vstrip) else '"'
    if vstrip.startswith("'"):
        return None if _SQ_CLOSED_RE.match(vstrip) else "'"
    return None


def _dq_closes(line: str) -> bool:
    """Есть ли в строке неэкранированная двойная кавычка (закрытие скаляра)."""
    esc = False
    for ch in line:
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            return True
    return False


def _flow_depth_delta(fragment: str) -> int:
    """Изменение глубины flow-скобок []/{} на фрагменте.

    Учитывает кавычки ('[lib]' внутри строки — не скобка; открытие кавычки
    гейтится предыдущим символом, чтобы апостроф в слове не «съедал» хвост)
    и комментарии (# вне кавычек обрывает строку). Круглые скобки не считаем —
    в YAML они не flow-разделители и встречаются в прозе.
    """
    depth = 0
    quote: str | None = None
    prev = " "
    for ch in fragment:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and prev in _QUOTE_GATE:
            quote = ch
        elif ch == "#" and prev.isspace():
            break
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        prev = ch
    return depth


def _find_inline_flow_dups(fragment: str) -> list:
    """Дубли ключей внутри ОДНОСТРОЧНОЙ сбалансированной flow-коллекции
    (`{a: 1, a: 2}` / `[{...}, {...}]`) — аудит 2026-08-03 FN-3: js-yaml
    вьюера падает и на flow-дубле, класс инцидента тот же, что STL-6.

    Стек контекстов: mapping ('{') трекает свой набор ключей, sequence ('[') —
    нет. Двоеточие — разделитель ключа только перед пробелом/','/'}'/']'/EOL
    или после quoted-токена (URL `http://x` — не ключ). Кавычки — с гейтом
    по предыдущему символу. Multi-line flow сюда не попадает (skip-режим).
    """
    dups: list[str] = []
    ctx: list[dict] = []          # {"kind": "m"|"s", "keys": dict|None}
    token = ""
    token_quoted = False
    quote: str | None = None
    prev = " "
    i, n = 0, len(fragment)
    while i < n:
        ch = fragment[i]
        if quote:
            if quote == "'" and ch == "'" and i + 1 < n and fragment[i + 1] == "'":
                token += "'"
                i += 2
                prev = "'"
                continue
            if quote == '"' and ch == "\\" and i + 1 < n:
                token += fragment[i + 1]
                i += 2
                prev = fragment[i - 1]
                continue
            if ch == quote:
                quote = None
            else:
                token += ch
        elif ch in "'\"" and prev in _QUOTE_GATE:
            quote = ch
            token = ""
            token_quoted = True
        elif ch == "{":
            ctx.append({"kind": "m", "keys": {}})
            token, token_quoted = "", False
        elif ch == "[":
            ctx.append({"kind": "s", "keys": None})
            token, token_quoted = "", False
        elif ch in "}]":
            if ctx:
                ctx.pop()
            token, token_quoted = "", False
        elif ch == ",":
            token, token_quoted = "", False
        elif ch == ":":
            nxt = fragment[i + 1] if i + 1 < n else " "
            if ctx and ctx[-1]["kind"] == "m" and (token_quoted or nxt in " ,}]"):
                key = token.strip()
                if key:
                    ks = ctx[-1]["keys"]
                    if key in ks:
                        dups.append(key)
                    else:
                        ks[key] = True
                token, token_quoted = "", False
            else:
                token += ch
        else:
            token += ch
        prev = ch
        i += 1
    return dups


def find_yaml_nested_duplicates(text: str) -> list:
    """Дубликаты mapping-ключей на любом уровне вложенности (STL-6).

    Возвращает [{key, path, depth, first_line, duplicate_line}] (строки 1-indexed;
    path — «родитель.цепочка», '[]' — элемент списка). Топ-левел дубли (depth 0)
    тоже включены — check_yaml_duplicates отфильтрует их, чтобы не дублировать
    исторический guard.

    Дизайн против ложных срабатываний (валидатор блокирующий):
      • каждый `- ` открывает СВЕЖИЙ scope элемента — повтор `id:`/`set_date:`
        в соседних элементах списка легален;
      • scope определяется отступом: одинаковый ключ под разными родителями
        живёт в разных scope-ах;
      • тела block scalars (`|`/`>`) пропускаются целиком (по отступу > ключа);
      • multi-line flow (`{...}`/`[...]` через строки) пропускается до баланса
        скобок (кавычки и комментарии учтены);
      • строки с табами в отступе пропускаются (в YAML это ошибка парсера,
        не наша зона);
      • duplicate-учёт ведётся для plain-ключей стандартного чарсета и
        quoted-ключей; экзотика (якоря, теги) в учёт не входит, но scope
        двигает.
    """
    if not isinstance(text, str):
        return []

    duplicates: list[dict] = []
    # Scope: {"indent": int, "keys": {key: line}, "path": tuple, "last_key": str|None}
    stack: list[dict] = [{"indent": 0, "keys": {}, "path": (), "last_key": None}]
    in_block_scalar = False
    block_scalar_indent = 0          # отступ КЛЮЧА, открывшего block scalar
    flow_depth = 0
    pending_quote: str | None = None  # многострочный quoted-скаляр (аудит FP-1)

    def _reset_stack() -> None:
        nonlocal stack
        stack = [{"indent": 0, "keys": {}, "path": (), "last_key": None}]

    def _emit_flow_dups(vfrag: str, lineno: int, scope_path: tuple) -> None:
        for dk in _find_inline_flow_dups(vfrag):
            duplicates.append({
                "key": dk,
                "path": ".".join(scope_path) or "<top>",
                "depth": max(1, len(scope_path)),
                "first_line": lineno,
                "duplicate_line": lineno,
            })

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if pending_quote:
            # тело многострочного quoted-скаляра — ждём закрывающую кавычку
            if pending_quote == '"':
                if _dq_closes(raw):
                    pending_quote = None
            else:
                if raw.count("'") % 2 == 1:
                    pending_quote = None
            continue

        if in_block_scalar:
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if "\t" in raw[:indent + 1]:
                continue
            if indent > block_scalar_indent:
                continue
            in_block_scalar = False
            # fall through — строка принадлежит обычному потоку

        if flow_depth > 0:
            flow_depth += _flow_depth_delta(raw)
            if flow_depth < 0:
                flow_depth = 0
            continue

        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("---", "..."):
            _reset_stack()
            continue

        indent = len(raw) - len(raw.lstrip(" "))
        if "\t" in raw[:indent + 1]:
            continue  # таб в отступе — не наша зона, YAML сам упадёт
        content = raw[indent:]
        line_indent = indent  # позиция первого дефиса (нужна block scalars в списках)

        # Раскрутить маркеры списка: каждый `- ` открывает новый scope элемента.
        while content.startswith("- ") or content == "-":
            while len(stack) > 1 and stack[-1]["indent"] > indent:
                stack.pop()
            parent = stack[-1]
            stack.append({
                "indent": indent + 2,
                "keys": {},
                "path": parent["path"]
                        + ((parent["last_key"],) if parent["last_key"] else ())
                        + ("[]",),
                "last_key": None,
            })
            if content == "-":
                content = ""
                break
            content = content[2:]
            indent += 2
            # пробелы сверх одного после дефиса
            extra = len(content) - len(content.lstrip(" "))
            if extra:
                content = content[extra:]
                indent += extra

        if not content or content.startswith("#"):
            continue

        # `- |` / `- >-` — block scalar как значение элемента списка (аудит FP-2):
        # тело скаляра не должно сканироваться как ключи.
        if _BLOCK_INDICATOR_ONLY_RE.match(content):
            in_block_scalar = True
            block_scalar_indent = line_indent
            continue

        # `- {…}` / `- […]` / flow-значение без ключа (аудит FN-3): гейт/дубли.
        if content[:1] in "[{":
            delta = _flow_depth_delta(content)
            if delta > 0:
                flow_depth = delta
            elif delta == 0:
                _emit_flow_dups(content, lineno, stack[-1]["path"])
            continue

        m = _NESTED_KEY_RE.match(content)
        if not m:
            # value-строка / продолжение скаляра — scope не трогаем
            continue

        key = m.group("dq") if m.group("dq") is not None else (
            m.group("sq") if m.group("sq") is not None else m.group("plain").strip()
        )

        while len(stack) > 1 and stack[-1]["indent"] > indent:
            stack.pop()
        if stack[-1]["indent"] == indent or len(stack) == 1 and indent == 0:
            scope = stack[-1]
        elif stack[-1]["indent"] < indent:
            parent = stack[-1]
            parent_name = parent["last_key"] or (parent["path"][-1] if parent["path"] else "")
            stack.append({
                "indent": indent,
                "keys": {},
                "path": parent["path"] + ((parent_name,) if parent["last_key"] else ()),
                "last_key": None,
            })
            scope = stack[-1]
        else:
            scope = stack[-1]

        trackable = bool(m.group("dq") is not None or m.group("sq") is not None
                         or _STRICT_KEY_RE.match(key))
        if trackable:
            if key in scope["keys"]:
                duplicates.append({
                    "key": key,
                    "path": ".".join(scope["path"]) or "<top>",
                    "depth": len(scope["path"]),
                    "first_line": scope["keys"][key],
                    "duplicate_line": lineno,
                })
            else:
                scope["keys"][key] = lineno
        scope["last_key"] = key

        value = content[m.end():]
        if _BLOCK_SCALAR_TAIL_RE.search(content):
            in_block_scalar = True
            block_scalar_indent = indent
            continue
        vstrip = value.strip()
        pq = _quoted_scalar_open(vstrip)
        if pq:
            pending_quote = pq          # многострочный quoted-скаляр (аудит FP-1)
            continue
        # Flow-гейт только когда значение РЕАЛЬНО начинается flow-коллекцией:
        # незакрытая '[' в прозе plain-скаляра — литерал, не flow (аудит FN-2).
        if vstrip[:1] in "[{":
            delta = _flow_depth_delta(vstrip)
            if delta > 0:
                flow_depth = delta
            elif delta == 0:
                _emit_flow_dups(vstrip, lineno,
                                scope["path"] + ((key,) if key else ()))

    return duplicates


def check_yaml_duplicates(payload: dict) -> dict:
    """CLI: проверка YAML-текста на дубликаты mapping-ключей (top-level + nested).

    Input: {"yaml_text": "..."} либо {"yaml_text": "...", "file": "name.yaml"}.
    Output: {"valid": bool, "duplicates": [...], "nested_duplicates": [...],
             "issues": [...]}.

    `issues` собран в формате остальных валидаторов (severity=blocking),
    чтобы save-to-library мог однообразно агрегировать. Top-level дубли идут
    из исторического guard'а; nested-слой (STL-6) добавляет только depth>0,
    чтобы не дублировать сообщения.
    """
    text = payload.get("yaml_text", "")
    file_id = payload.get("file") or "<inline>"
    dups = find_yaml_top_level_duplicates(text)
    # depth-0 отдаётся историческому guard'у ТОЛЬКО для ключей, которые он
    # реально видит (strict-чарсет); quoted/не-strict top-level дубли
    # ("2026": ×2, foo.bar: ×2) иначе терялись обоими слоями (аудит FN-1).
    nested = [d for d in find_yaml_nested_duplicates(text)
              if d["depth"] > 0 or not _STRICT_KEY_RE.match(d["key"])]
    issues = [
        {
            "field": f"yaml:{file_id}",
            "severity": "blocking",
            "expected": "уникальные top-level ключи",
            "actual": (
                f"дубликат '{d['key']}': первое вхождение строка {d['first_line']}, "
                f"повтор строка {d['duplicate_line']}"
            ),
            "key": d["key"],
            "first_line": d["first_line"],
            "duplicate_line": d["duplicate_line"],
        }
        for d in dups
    ]
    issues += [
        {
            "field": f"yaml:{file_id}",
            "severity": "blocking",
            "expected": "уникальные ключи внутри одного mapping-scope",
            "actual": (
                f"вложенный дубликат '{d['key']}' (scope {d['path']}): "
                f"первое вхождение строка {d['first_line']}, повтор строка {d['duplicate_line']}"
            ),
            "key": d["key"],
            "path": d["path"],
            "first_line": d["first_line"],
            "duplicate_line": d["duplicate_line"],
        }
        for d in nested
    ]
    return {
        "valid": len(issues) == 0,
        "blocking_count": len(issues),
        "duplicates": dups,
        "nested_duplicates": nested,
        "issues": issues,
    }


# Canonical subfolder → subdomain mapping (from subfolder-mapping.md)
SUBFOLDER_SUBDOMAINS: dict[str, set[str]] = {
    "geopolitics": {
        "long-term-russia", "short-term-russia", "eu-future", "china-collapse",
        "china-rise", "middle-east", "iran", "us-domestic", "nato-future",
        "nuclear-proliferation", "migration-eu",
    },
    "ru-sellside": {
        "iis-targets", "long-term-strategy", "oil-gas-ru", "metals-mining-ru",
        "it-tech-ru", "finance-ru", "consumer-ru", "bonds-rub", "bonds-fx",
        "dividend-stocks", "small-caps-ru", "etfs-ru",
    },
    "global-banks": {
        "us-equities", "european-equities", "emerging-markets", "oil-forecast",
        "commodities-non-oil", "currency-forecasts", "ny-rates", "crypto",
        "ai-stocks-bubble", "recession-call", "sector-rotation",
    },
    "tech-ceo": {
        "agi-timeline", "model-capability", "regulation-ai", "compute-economics",
        "crypto", "space-tech", "biotech-future",
    },
    "ru-macro": {
        "ru-rates-forecast", "ru-inflation", "usd-rub-forecast", "cny-rub-forecast",
        "ru-budget", "ru-economy-growth", "ru-banking-system",
    },
    "commodity-agencies": {
        "oil-market", "gas-market", "lng", "metals", "coal", "agricultural",
        "iea-omr", "opec-omr", "energy-transition", "oil-demand", "oil-supply",
    },
}

VALID_TRUST_LEVELS = {"HIGH", "MEDIUM", "LOW", "IGNORE"}

TRUST_3D_DIMENSIONS = ("marginal", "world_picking", "conditional")


def flatten_trust(trust: object) -> dict:
    """Normalize trust to flat {subdomain: level} dict.

    DEPRECATED noop after D8 (CLAUDE.md, 2026-05-10): trust остаётся плоским 1D.
    Функция сохранена для backward-compat: если приходит legacy 3D-dict
    (`{marginal: {...}, world_picking: {...}, conditional: {...}}`), возвращает
    `trust['marginal']`. Plain 1D dict → возвращается как есть.
    Не вызывается из нового кода — все новые profiles 1D.
    """
    if not isinstance(trust, dict):
        return {}
    if (
        trust
        and set(trust.keys()).issubset(set(TRUST_3D_DIMENSIONS))
        and all(isinstance(v, (dict, type(None))) for v in trust.values())
    ):
        return dict(trust.get("marginal") or {})
    return trust
VALID_METHODS = {"fca", "manual", "external_quoted"}
VALID_DOMAINS = {"geopolitics", "ru-macro", "ru-sellside", "global-banks", "tech-ceo", "commodity-agencies"}


def _blocking(issues: list) -> list:
    return [i for i in issues if i["severity"] == "blocking"]


# ---------------------------------------------------------------------------
# validate-stress (E3)
# ---------------------------------------------------------------------------

def _validate_stress_bond_carry(
    data: dict, scenarios, per_position, issues: list,
) -> None:
    """Слой 2 total-return: аддитивный блок bond_carry (compute_bond_carry.py).

    Блок опционален (старые артефакты без него валидны). Если присутствует:
    - schema == 'bond-carry@1', per_position непуст;
    - scenario-ID ячеек ⊆ scenarios (orphan → blocking);
    - анти-двойной-счёт: бумага с matures_within на горизонте обязана иметь
      обнулённый price_delta в per_position stress (maturity guard) — иначе
      тело сидит в обоих слоях → blocking `double_count_risk`.
    Обратный дрейф: price_delta_zeroed в stress без bond_carry-блока → warning
    (доход обнулённых бумаг потерян).
    """
    bc = data.get("bond_carry")
    if bc is None:
        # maturity guard без carry-слоя: обнулённая цена и НЕТ carry → дыра в total
        if isinstance(per_position, dict):
            zeroed = [
                t for t, pos in per_position.items()
                if isinstance(pos, dict) and any(
                    isinstance(hv, dict) and hv.get("price_delta_zeroed")
                    for hv in (pos.get("by_horizon") or {}).values()
                )
            ]
            if zeroed:
                issues.append({
                    "field": "bond_carry",
                    "severity": "warning",
                    "expected": "блок bond_carry (compute_bond_carry.py) при "
                                "обнулённых price_delta",
                    "actual": f"отсутствует, но price_delta_zeroed у: {sorted(zeroed)} "
                              f"— их доход не учтён ни одним слоем",
                })
        return

    if not isinstance(bc, dict):
        issues.append({
            "field": "bond_carry", "severity": "blocking",
            "expected": "dict (выход compute_bond_carry.py)",
            "actual": type(bc).__name__,
        })
        return
    if bc.get("schema") != "bond-carry@1":
        issues.append({
            "field": "bond_carry.schema", "severity": "blocking",
            "expected": "'bond-carry@1'", "actual": str(bc.get("schema")),
        })
    carry_pp = bc.get("per_position")
    if not carry_pp or not isinstance(carry_pp, dict):
        issues.append({
            "field": "bond_carry.per_position", "severity": "blocking",
            "expected": "non-empty dict {ticker: {kind, by_horizon}}",
            "actual": type(carry_pp).__name__ if carry_pp is not None else None,
        })
        return

    scenario_keys = set(scenarios.keys()) if isinstance(scenarios, dict) else set()
    for ticker, entry in carry_pp.items():
        if not isinstance(entry, dict):
            continue
        for hk, hv in (entry.get("by_horizon") or {}).items():
            if not isinstance(hv, dict):
                continue
            if scenario_keys:
                orphan = set((hv.get("by_scenario") or {}).keys()) - scenario_keys
                if orphan:
                    issues.append({
                        "field": f"bond_carry.per_position.{ticker}.by_horizon.{hk}",
                        "severity": "blocking",
                        "expected": f"scenario keys in {sorted(scenario_keys)}",
                        "actual": f"orphan IDs: {sorted(orphan)}",
                    })
            # Анти-двойной-счёт: carry несёт тело (matures_within) → цена обнулена
            if entry.get("kind") == "bond" and hv.get("matures_within"):
                pos = per_position.get(ticker) if isinstance(per_position, dict) else None
                slot = ((pos or {}).get("by_horizon") or {}).get(hk)
                if not isinstance(slot, dict):
                    issues.append({
                        "field": f"bond_carry.per_position.{ticker}.by_horizon.{hk}",
                        "severity": "warning",
                        "expected": f"позиция {ticker} с горизонтом {hk} в stress per_position",
                        "actual": "нет среза — сверка двойного счёта невозможна",
                    })
                    continue
                deltas = slot.get("delta_pct_by_scenario") or {}
                all_zero = all(
                    (d.get("value") if isinstance(d, dict) else d) in (0, 0.0)
                    for d in deltas.values()
                ) if deltas else False
                if not slot.get("price_delta_zeroed") and not all_zero:
                    issues.append({
                        "field": f"per_position.{ticker}.by_horizon.{hk}",
                        "severity": "blocking",
                        "expected": "price_delta_zeroed (maturity guard): бумага "
                                    "гасится внутри горизонта, тело уже в bond_carry "
                                    "(pull-to-par/реинвест)",
                        "actual": "double_count_risk: ненулевой price_delta + carry "
                                  "с matures_within на одном горизонте",
                    })


# Контракт баз расчёта (2026-09-18, docs/investment/task-stress-basis-contract.md
# §11.2a yaml-schemas.md). Полная арифметическая проверка (RECONCILE, требует
# снапшот + input_contract.py) живёт в
# skills/portfolio-scenario-stress/scripts/validate_stress_output.py и
# прогоняется ДО этой точки — Pre-emit checklist SKILL.md шаг 6 требует exit 0
# перед вызовом save-to-library. Здесь — только лёгкая структурная сверка имён
# native Python (без cross-skill импорта — скиллы упаковываются независимо,
# `pack.sh` не тянет чужие scripts/). WARNING, не blocking: `_v2_stress()`
# базовая фикстура тестов E3 старше этого контракта, промотать в blocking —
# отдельный шаг вместе с обновлением фикстуры (см. save-to-library-fixes.md).
_STRESS_BASIS_FORBIDDEN_TOP_LEVEL = {
    "expected_pl_rub": "portfolio_aggregates.{price,total_return}.expected_pl_rub_by_horizon",
    "portfolio_pl_range_rub": "portfolio_aggregates.{price,total_return}.pl_range_rub_by_horizon",
    "total_return_by_horizon_rub": "scenarios.<X>.portfolio_level_by_horizon.<hNN>.total_return_rub",
}
_STRESS_BASIS_FORBIDDEN_CELL = {
    "delta_rub": "price_delta_rub и total_return_rub — оба явно",
    "l1_price_only_delta_rub": "price_delta_rub",
    "l1_price_only_pct": "price_delta_pct",
    "expected_pct_pweighted": "portfolio_aggregates.<basis>.expected_pl_pct_by_horizon",
}


def _validate_stress_basis_contract(data: dict, scenarios, issues: list) -> None:
    for field in ("basis_contract", "per_position_basis", "base_value_rub", "p_basis"):
        if field not in data:
            issues.append({
                "field": field, "severity": "warning",
                "expected": "контракт баз расчёта §11.2a yaml-schemas.md "
                            "(строгая проверка — validate_stress_output.py на генерации)",
                "actual": "отсутствует",
            })
    for key, replacement in _STRESS_BASIS_FORBIDDEN_TOP_LEVEL.items():
        if key in data:
            issues.append({
                "field": key, "severity": "warning",
                "expected": f"использовать {replacement} (§11.2a)",
                "actual": "deprecated top-level поле присутствует",
            })
    if isinstance(scenarios, dict):
        for sid, sc in scenarios.items():
            if not isinstance(sc, dict):
                continue
            for hk, cell in (sc.get("portfolio_level_by_horizon") or {}).items():
                if not isinstance(cell, dict):
                    continue
                for key, replacement in _STRESS_BASIS_FORBIDDEN_CELL.items():
                    if key in cell:
                        issues.append({
                            "field": f"scenarios.{sid}.portfolio_level_by_horizon.{hk}.{key}",
                            "severity": "warning",
                            "expected": f"использовать {replacement} (§11.2a)",
                            "actual": "deprecated поле присутствует",
                        })


def validate_stress(data: dict) -> dict:
    """Validate portfolio stress-test YAML (E3). Только schema_version 2 —
    v1-приём снят V2-CUTOVER 2026-08-03 (библиотека мигрирована wrap-as-single-horizon;
    мигратор: skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py)."""
    issues: list[dict] = []
    sv = data.get("schema_version")
    v2 = (sv == 2 and not isinstance(sv, bool))

    # Required scalar fields
    for field, check, expected_desc in [
        ("schema_version", lambda v: v == 2 and not isinstance(v, bool),
         "must equal 2 (v1 снят V2-CUTOVER 2026-08-03 — migrate_v1_to_v2.py)"),
        ("type", lambda v: v == "portfolio-stress-test", "must equal 'portfolio-stress-test'"),
        ("date", lambda v: bool(v), "required non-empty"),
        ("portfolio_snapshot_id", lambda v: bool(v), "required non-empty"),
        ("weight_type", lambda v: v in ("equal", "probability"), "must be 'equal' or 'probability'"),
    ]:
        val = data.get(field)
        if val is None or not check(val):
            issues.append({
                "field": field,
                "severity": "blocking",
                "expected": expected_desc,
                "actual": str(val) if val is not None else None,
            })

    # Ссылка на макросценарии (schema.md §4.6, R22): одно поле macro_input — имя файла macro-chain;
    # второго имени нет, версии прогнозов в стресс не копируются (на них ссылаются макросценарии)
    if "macro_scenarios_file" in data:
        issues.append({"field": "macro_scenarios_file", "severity": "blocking",
                       "expected": "ссылка на макросценарии — поле macro_input (R22)",
                       "actual": str(data.get("macro_scenarios_file"))})
    mi = data.get("macro_input")
    if mi is not None and not (isinstance(mi, str) and mi.strip()):
        issues.append({"field": "macro_input", "severity": "blocking",
                       "expected": "имя файла macro-chain/macro-scenarios-<дата>.yaml (строка) или null",
                       "actual": str(mi)})
    elif not mi and data.get("scenario_source") == "macro-forecast-chain":
        issues.append({"field": "macro_input", "severity": "warning",
                       "expected": "имя файла макросценариев (build_stress_stub.py --macro-scenarios) — "
                                   "без него вьюер покажет «ссылка не записана»",
                       "actual": None})

    # v2: горизонт-блок + анти-möbius drift (v1-поля горизонта)
    if v2:
        _validate_horizons_block(data, issues)
        _check_v1_horizon_fields_in_v2(data, issues)

    # scenarios
    scenarios = data.get("scenarios")
    if not scenarios or not isinstance(scenarios, dict):
        issues.append({
            "field": "scenarios",
            "severity": "blocking",
            "expected": "dict with Sc-X keys",
            "actual": None,
        })
    else:
        # Anti-drift renames (2026-05-12 Opus gen incident):
        # - label вместо name; probability вместо p
        # - плоский pnl_rub / delta_pct на уровне сценария вместо portfolio_level
        for sid, sc in scenarios.items():
            if not isinstance(sc, dict):
                continue
            if "label" in sc and "name" not in sc:
                issues.append({
                    "field": f"scenarios.{sid}.label",
                    "severity": "blocking",
                    "expected": "canonical field name: 'name' (NOT 'label')",
                    "actual": "drift-rename 'label' (used by Opus gen 2026-05-12)",
                })
            if "probability" in sc and "p" not in sc:
                issues.append({
                    "field": f"scenarios.{sid}.probability",
                    "severity": "blocking",
                    "expected": "canonical field name: 'p' (NOT 'probability')",
                    "actual": "drift-rename 'probability' (used by Opus gen 2026-05-12)",
                })
            # pnl_rub / delta_pct flat вместо portfolio_level
            pl = sc.get("portfolio_level")
            has_flat_pnl = "pnl_rub" in sc and not (isinstance(pl, dict) and "delta_rub" in pl)
            has_flat_delta = "delta_pct" in sc and not (isinstance(pl, dict) and "expected_pct_pweighted" in pl)
            if has_flat_pnl:
                issues.append({
                    "field": f"scenarios.{sid}.pnl_rub",
                    "severity": "blocking",
                    "expected": "wrap in portfolio_level: {delta_rub: <value>, expected_pct_pweighted: ...}",
                    "actual": "flat 'pnl_rub' at scenario top-level (drift)",
                })
            if has_flat_delta:
                issues.append({
                    "field": f"scenarios.{sid}.delta_pct",
                    "severity": "blocking",
                    "expected": "wrap in portfolio_level: {delta_rub: ..., expected_pct_pweighted: <value>}",
                    "actual": "flat 'delta_pct' at scenario top-level (drift)",
                })
            # v2: factors → factors_by_horizon; portfolio_level → portfolio_level_by_horizon
            if v2:
                if "factors" in sc:
                    issues.append({
                        "field": f"scenarios.{sid}.factors",
                        "severity": "blocking",
                        "expected": "factors_by_horizon: {hNN: {...}} (v2)",
                        "actual": "v1_field_in_v2: плоский 'factors' вместо factors_by_horizon",
                    })
                if "portfolio_level" in sc:
                    issues.append({
                        "field": f"scenarios.{sid}.portfolio_level",
                        "severity": "blocking",
                        "expected": "portfolio_level_by_horizon: {hNN: {...}} (v2)",
                        "actual": "v1_field_in_v2: плоский 'portfolio_level'",
                    })
                fbh = sc.get("factors_by_horizon")
                if not isinstance(fbh, dict) or not fbh:
                    issues.append({
                        "field": f"scenarios.{sid}.factors_by_horizon",
                        "severity": "blocking",
                        "expected": "dict {hNN: {factor: delta}}",
                        "actual": str(type(fbh).__name__),
                    })
                else:
                    bad = [k for k in fbh if not re.match(r"^h\d+$", str(k))]
                    if bad:
                        issues.append({
                            "field": f"scenarios.{sid}.factors_by_horizon",
                            "severity": "blocking",
                            "expected": "ключи вида h<NN>",
                            "actual": f"невалидные ключи: {bad}",
                        })

        # Sum of probabilities (warning, not blocking — rounding tolerance ±1%)
        try:
            prob_sum = sum(
                float(v["p"]) if isinstance(v, dict) and "p" in v else 0
                for v in scenarios.values()
            )
            if not (0.98 <= prob_sum <= 1.02):
                issues.append({
                    "field": "scenarios[*].p",
                    "severity": "warning",
                    "expected": "sum in [0.99, 1.01]",
                    "actual": f"{prob_sum:.4f}",
                })
        except (TypeError, ValueError):
            pass

    # per_position
    per_position = data.get("per_position")
    if not per_position or not isinstance(per_position, dict):
        issues.append({
            "field": "per_position",
            "severity": "blocking",
            "expected": "dict with ticker keys",
            "actual": None,
        })
    else:
        # Coverage: Σ weight_pct + cash_pct + blocked_pct ∈ [98, 102]
        try:
            weight_sum = sum(
                float(v["weight_pct"]) if isinstance(v, dict) and "weight_pct" in v else 0
                for v in per_position.values()
            )
            cash = float(data.get("cash_pct", 0))
            blocked = float(data.get("blocked_pct", 0))
            total = weight_sum + cash + blocked
            if total < 98:
                issues.append({
                    "field": "per_position coverage",
                    "severity": "blocking",
                    "expected": "sum weight_pct + cash_pct + blocked_pct ≥ 98%",
                    "actual": f"{total:.1f}%",
                })
            elif total > 102:
                issues.append({
                    "field": "per_position coverage",
                    "severity": "blocking",
                    "expected": "sum weight_pct + cash_pct + blocked_pct ≤ 102% (possible double-count)",
                    "actual": f"{total:.1f}%",
                })
        except (TypeError, ValueError):
            pass

        # Scenario IDs cross-reference (v2 — внутри by_horizon.{hNN})
        if scenarios and isinstance(scenarios, dict):
            scenario_keys = set(scenarios.keys())
            for ticker, pos in per_position.items():
                if not isinstance(pos, dict):
                    continue
                if v2:
                    for hk, hv in (pos.get("by_horizon") or {}).items():
                        delta_keys = set((hv or {}).get("delta_pct_by_scenario", {}).keys())
                        orphan = delta_keys - scenario_keys
                        if orphan:
                            issues.append({
                                "field": f"per_position.{ticker}.by_horizon.{hk}.delta_pct_by_scenario",
                                "severity": "blocking",
                                "expected": f"keys in {sorted(scenario_keys)}",
                                "actual": f"orphan IDs: {sorted(orphan)}",
                            })
                else:
                    delta_keys = set(pos.get("delta_pct_by_scenario", {}).keys())
                    orphan = delta_keys - scenario_keys
                    if orphan:
                        issues.append({
                            "field": f"per_position.{ticker}.delta_pct_by_scenario",
                            "severity": "blocking",
                            "expected": f"keys in {sorted(scenario_keys)}",
                            "actual": f"orphan IDs: {sorted(orphan)}",
                        })

    # caveats: must exist and contain ≥1 entry with severity: HIGH
    caveats = data.get("caveats")
    if not caveats or not isinstance(caveats, list):
        issues.append({
            "field": "caveats",
            "severity": "blocking",
            "expected": "list with ≥1 entry having severity: HIGH",
            "actual": None,
        })
    else:
        if not any(isinstance(c, dict) and c.get("severity") == "HIGH" for c in caveats):
            issues.append({
                "field": "caveats",
                "severity": "blocking",
                "expected": "at least 1 entry with severity: HIGH",
                "actual": f"{len(caveats)} caveats, none with severity=HIGH",
            })

    # macro_blindspots: all tickers must be in per_position
    macro_blindspots = data.get("macro_blindspots")
    if macro_blindspots and isinstance(macro_blindspots, list) and per_position:
        missing = [t for t in macro_blindspots if isinstance(t, str) and t not in per_position]
        if missing:
            issues.append({
                "field": "macro_blindspots",
                "severity": "warning",
                "expected": "all tickers present in per_position",
                "actual": f"not in per_position: {missing}",
            })

    # unmapped_tickers: ключ обязателен (Pre-emit checklist в SKILL.md:505),
    # значение может быть пустым списком, но сам ключ должен присутствовать.
    if "unmapped_tickers" not in data:
        issues.append({
            "field": "unmapped_tickers",
            "severity": "blocking",
            "expected": "list (may be empty) — required by Pre-emit checklist",
            "actual": None,
        })
    elif not isinstance(data.get("unmapped_tickers"), list):
        issues.append({
            "field": "unmapped_tickers",
            "severity": "blocking",
            "expected": "list type",
            "actual": type(data.get("unmapped_tickers")).__name__,
        })
    elif data["unmapped_tickers"]:
        # Чувствительность задаётся ВСЕМ бумагам портфеля: бумага в unmapped_tickers в расчёт не входит,
        # и стресс молча недосчитывает её вес. Стрессы старше STRESS_UNMAPPED_SINCE сохранялись по прежнему
        # правилу («исключить с флагом») и остаются валидными — для них только warning.
        names = [str(u.get("ticker") if isinstance(u, dict) else u) for u in data["unmapped_tickers"]]
        new_rule = str(data.get("date") or "") >= STRESS_UNMAPPED_SINCE
        issues.append({
            "field": "unmapped_tickers",
            "severity": "blocking" if new_rule else "warning",
            "expected": "[] — чувствительность (factor_betas) задана каждой бумаге портфеля",
            "actual": f"без чувствительности: {', '.join(names)}",
        })

    # generated_at vs date: явная ошибка — если есть generated_at но нет date
    if "generated_at" in data and "date" not in data:
        issues.append({
            "field": "date",
            "severity": "blocking",
            "expected": "top-level 'date' (NOT 'generated_at') — see SKILL.md Pre-emit checklist",
            "actual": "found 'generated_at' instead",
        })

    # v2: baseline_spot — потребители L1-overlay (integrated-view, MFC-4) и
    # compute_bond_carry (уровень КС). Отсутствие не блокирует (старый флоу),
    # но L1 молча деградирует в L2 → warning.
    if v2 and not isinstance(data.get("baseline_spot"), dict):
        issues.append({
            "field": "baseline_spot",
            "severity": "warning",
            "expected": "dict спотов (brent_usd, usdrub, cnyrub, cbr_rate_pct, xauusd_usd)",
            "actual": "отсутствует — L1-overlay integrated-view деградирует в L2; "
                      "carry-слой требует уровень КС отдельным входом",
        })

    # ── bond_carry (Слой 2 total-return, аддитивный блок) ──
    _validate_stress_bond_carry(data, scenarios, per_position, issues)

    # ── контракт баз расчёта (2026-09-18, §11.2a) — warning, см. docstring выше ──
    if v2:
        _validate_stress_basis_contract(data, scenarios, issues)

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "warning_count": len(issues) - len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# validate-forecast (B3 + B4.1a)
# ---------------------------------------------------------------------------

def validate_forecast_frontmatter(data: dict) -> dict:
    """Validate forecast .md frontmatter required fields (B3 + B4.1a logic)."""
    issues: list[dict] = []

    for field in ("forecast_date", "horizon_date", "review_interval_months", "topic", "domain", "method"):
        if not data.get(field):
            issues.append({
                "field": field,
                "severity": "blocking",
                "expected": "non-empty value",
                "actual": None,
            })

    # horizon_date must not be a TODO placeholder
    horizon = str(data.get("horizon_date", ""))
    if "TODO" in horizon.upper():
        issues.append({
            "field": "horizon_date",
            "severity": "blocking",
            "expected": "real YYYY-MM-DD date, not TODO",
            "actual": horizon,
        })

    domain = data.get("domain")
    if domain and domain not in VALID_DOMAINS:
        issues.append({
            "field": "domain",
            "severity": "blocking",
            "expected": f"one of {sorted(VALID_DOMAINS)}",
            "actual": domain,
        })

    method = data.get("method")
    if method and method not in VALID_METHODS:
        issues.append({
            "field": "method",
            "severity": "blocking",
            "expected": f"one of {sorted(VALID_METHODS)}",
            "actual": method,
        })

    # B4.1a: method=fca requires confidence in [0, 1]
    if method == "fca":
        confidence = data.get("confidence")
        if confidence is None:
            issues.append({
                "field": "confidence",
                "severity": "blocking",
                "expected": "numeric in [0, 1] — required for method=fca",
                "actual": None,
                "action": "show menu [A]/[B]/[C] from B4.1a",
            })
        else:
            try:
                conf_val = float(confidence)
                if not (0 <= conf_val <= 1):
                    issues.append({
                        "field": "confidence",
                        "severity": "blocking",
                        "expected": "value in [0.0, 1.0]",
                        "actual": str(confidence),
                    })
            except (TypeError, ValueError):
                issues.append({
                    "field": "confidence",
                    "severity": "blocking",
                    "expected": "numeric float in [0, 1]",
                    "actual": str(confidence),
                })

    # schema_version: informational auto-set note
    if not data.get("schema_version"):
        issues.append({
            "field": "schema_version",
            "severity": "info",
            "expected": "1",
            "actual": None,
            "action": "auto-set to 1",
        })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# validate-audit (A2)
# ---------------------------------------------------------------------------

def validate_audit_frontmatter(data: dict) -> dict:
    """Validate audit source frontmatter required fields (A2 logic)."""
    issues: list[dict] = []

    for field in ("source", "audit_date", "trust"):
        if not data.get(field):
            issues.append({
                "field": field,
                "severity": "blocking",
                "expected": "non-empty value",
                "actual": None,
            })

    raw_trust = data.get("trust", {})
    if isinstance(raw_trust, dict):
        # 3D format support (D4): validate every dimension that's present.
        is_3d = (
            raw_trust
            and set(raw_trust.keys()).issubset(set(TRUST_3D_DIMENSIONS))
            and all(isinstance(v, (dict, type(None))) for v in raw_trust.values())
        )
        if is_3d:
            for dim in TRUST_3D_DIMENSIONS:
                dim_trust = raw_trust.get(dim) or {}
                if not isinstance(dim_trust, dict):
                    continue
                for subdomain, level in dim_trust.items():
                    if level not in VALID_TRUST_LEVELS:
                        issues.append({
                            "field": f"trust.{dim}.{subdomain}",
                            "severity": "warning",
                            "expected": f"one of {sorted(VALID_TRUST_LEVELS)}",
                            "actual": level,
                        })
        else:
            for subdomain, level in raw_trust.items():
                if level not in VALID_TRUST_LEVELS:
                    issues.append({
                        "field": f"trust.{subdomain}",
                        "severity": "warning",
                        "expected": f"one of {sorted(VALID_TRUST_LEVELS)}",
                        "actual": level,
                    })
    elif raw_trust:
        issues.append({
            "field": "trust",
            "severity": "blocking",
            "expected": "dict of subdomain → trust_level (or 3D: marginal/world_picking/conditional)",
            "actual": str(type(raw_trust)),
        })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# determine-subfolder (A3)
# ---------------------------------------------------------------------------

def determine_subfolder(trust: dict) -> dict:
    """Determine subfolder from trust subdomains (A3 logic)."""
    if not trust:
        return {"recommended": None, "ambiguous": True, "reason": "empty trust dict", "counts": {}}

    active = {k for k, v in trust.items() if v != "IGNORE"}
    counts = {
        folder: len(active & subs)
        for folder, subs in SUBFOLDER_SUBDOMAINS.items()
        if active & subs
    }
    unmatched = sorted(active - set().union(*SUBFOLDER_SUBDOMAINS.values()))

    if not counts:
        return {
            "recommended": None,
            "ambiguous": True,
            "reason": "no subdomains matched any canonical folder",
            "counts": {},
            "unmatched": unmatched,
        }

    max_count = max(counts.values())
    top = [f for f, c in counts.items() if c == max_count]

    if len(top) == 1:
        return {"recommended": top[0], "ambiguous": False, "counts": counts}
    return {
        "recommended": None,
        "ambiguous": True,
        "reason": f"tie between {top} (each {max_count} matches)",
        "counts": counts,
        "candidates": top,
    }


# ---------------------------------------------------------------------------
# compute-inclusion (A4)
# ---------------------------------------------------------------------------

def compute_inclusion(pin: bool, trust: dict) -> dict:
    """Check auto-inclusion: pin=true OR any trust=HIGH (A4 logic)."""
    if pin:
        return {"include_in_memory": True, "reason": "pin=true"}
    high = sorted(k for k, v in trust.items() if v == "HIGH")
    if high:
        return {"include_in_memory": True, "reason": f"trust HIGH in: {', '.join(high)}"}
    return {"include_in_memory": False, "reason": "pin=false and no HIGH trust subdomains"}


# ---------------------------------------------------------------------------
# validate-weekly-review (F) — router + detailed stock/bond validators
# ---------------------------------------------------------------------------
#
# Архитектура (после 2026-05-12 incident — drift Opus model gen):
# - validate_weekly_review = роутер по полю `type`:
#     weekly-stocks-review → validate_weekly_review_stock_detailed
#     weekly-bonds-review  → validate_weekly_review_bond_detailed
#     неизвестный/legacy   → базовый чек (review_date + snapshot_id + per_*)
# - validate_weekly_review_stock_detailed: блокирует, если
#     • TODO_LLM плейсхолдер остался незаменённым
#     • required-поле отсутствует/null/неверный тип
#     • применено drift-имя (share_actual_pct, ie_share_pct, delta_pct, catalysts)
# - validate_weekly_review_bond_detailed: аналогично для bond YAML

VALID_FUNDAMENTAL_SCORE = {"HIGH", "MEDIUM", "LOW", "RED_FLAG"}
VALID_LEVEL_HML = {"HIGH", "MEDIUM", "LOW"}
# Вердикты обзора недели — коды кодлиста verdict, допускаемые для класса (поле `weekly`).
VALID_ADVISOR_VERDICT_STOCK = set(codelists.where("verdict", "weekly", "stock"))
VALID_BOND_TYPE = {"ofz", "corp_rub", "fx_replacement", "floater", "perpetual"}
# STL-7/8 (bond-subtypes-plan.md §4.3): плановая таксономия владельца — plan_bucket/
# plan_subtype — опциональна и ортогональна VALID_BOND_TYPE выше, её не заменяет.
# None в множестве подтипов = валютные корзины (USD/EUR/CNY) несут plan_subtype: null.
VALID_PLAN_BUCKET_SUBTYPE = {
    "USD": {None},
    "EUR": {None},
    "CNY": {None},
    "ОФЗ": {">10", "<10", "Флоат"},
    "КОРП": {"AA+", "A", "B+", "Флоат"},  # Флоат структурно разрешён (решение Q4)
}
# per_bond[ISIN].rating (bond-subtypes-plan.md §4.5): лестница §4.2 + «нет рейтинга»; агентства национальной шкалы
VALID_BOND_RATING_VALUES = {
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
    "нет рейтинга",
}
VALID_RATING_AGENCIES = {"АКРА", "Эксперт РА", "НКР", "НРА"}
# Облигации — единый словарь вердиктов (schema.md §3.4): коды с пометкой `weekly` для облигаций (включая WATCH);
# legacy-коды несут ту же пометку только до переключения (данные мигрируются в шаге 17), нормой не являются.
VALID_ADVISOR_VERDICT_BOND = set(codelists.where("verdict", "weekly", "bond"))
# Слой 3 total-return: dividend_forward (опциональный блок per_stock, 2026-07)
VALID_DIV_POLICY_STATE = {"declared", "expected", "suspended", "none", "uncertain"}
VALID_DIV_YEAR2_BASIS = {"analyst", "carry_forward", "none"}
DIV_FORWARD_STALE_DAYS = 56  # as_of старше 8 недель от review_date → warning stale

# Drift-имена, которые Opus model gen использовал 2026-05-12 — детектим в per_stock/per_bond entries.
STOCK_DRIFT_FIELDS = {
    "share_actual_pct": "weight_real_pct",
    "ie_share_pct": "weight_ie_target_pct",
    "delta_pct": "weight_divergence_pp",
    "catalysts": "catalyst",
    # RPA-19 (2026-08-20): плановая доля владельца. Имена ниже — как поле называется
    # в снапшоте (`ie_actual.per_ticker[t].planned_share_pct`) и вероятные сокращения;
    # скопировать их в обзор дословно — типовой дрейф.
    "planned_share_pct": "weight_user_planned_pct",
    "user_planned_pct": "weight_user_planned_pct",
    "weight_planned_pct": "weight_user_planned_pct",
    "divergence_vs_planned_pp": "weight_divergence_vs_planned_pp",
    "divergence_vs_ie_pp": "weight_divergence_vs_ie_pp",
}

# RPA-19: допуск сверки «real − target == divergence» в пп. Поля заполняет
# build_weekly_stock_stub.py с округлением до 4 знаков; расхождение больше допуска
# означает, что число правили руками, не тронув слагаемые.
WEIGHT_DIVERGENCE_TOLERANCE_PP = 0.05
BOND_DRIFT_TOP_LEVEL = {
    # summary.bonds_total_rub → summary.total_value_rub
    "bonds_total_rub": "total_value_rub",
}


def _check_weight_divergence_consistency(entry: dict, path: str, issues: list) -> None:
    """RPA-19: расхождение обязано быть разностью своих слагаемых, а не отдельным числом.

    Три сверки: real − planned == divergence_vs_planned, real − ie == divergence_vs_ie,
    и deprecated `weight_divergence_pp` == `weight_divergence_vs_ie_pp`. Каждая работает
    только когда оба слагаемых непусты; null-ы пропускаются молча (бумаги вне модели IE
    и позиции без плана — штатный случай).
    """
    def num(name):
        v = entry.get(name)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    real = num("weight_real_pct")
    for target_field, div_field in (("weight_user_planned_pct", "weight_divergence_vs_planned_pp"),
                                    ("weight_ie_target_pct", "weight_divergence_vs_ie_pp")):
        target, div = num(target_field), num(div_field)
        if real is None or target is None or div is None:
            continue
        if abs((real - target) - div) > WEIGHT_DIVERGENCE_TOLERANCE_PP:
            issues.append({
                "field": f"{path}.{div_field}",
                "severity": "blocking",
                "expected": f"weight_real_pct − {target_field} = {round(real - target, 4)}",
                "actual": str(div),
            })

    ie_div, legacy = num("weight_divergence_vs_ie_pp"), num("weight_divergence_pp")
    if ie_div is not None and legacy is not None and abs(ie_div - legacy) > WEIGHT_DIVERGENCE_TOLERANCE_PP:
        issues.append({
            "field": f"{path}.weight_divergence_pp",
            "severity": "blocking",
            "expected": f"алиас weight_divergence_vs_ie_pp = {ie_div}",
            "actual": str(legacy),
        })


def _is_todo_llm(v: object) -> bool:
    """True, если значение — невыполненный TODO_LLM плейсхолдер."""
    if isinstance(v, str) and v.startswith("TODO_LLM"):
        return True
    return False


_WEEK_NOTE_KEYS = {"what_happened", "recommendation", "macro_link"}
CONFIDENCE_BASIS_FROM = 0.8   # ниже — нужна причина «что снижает уверенность» (решение владельца 26.10)


def _week_note_and_confidence_checks(entry: dict, path: str, issues: list) -> None:
    """Аддитивные поля бумаги (план переосмысления вьюера, 2026-10-26):
    - `week_note` (контракт A, пишет render_weekly_md --embed-notes): {what_happened: [str], recommendation:
      [str]|null, macro_link: str|null}; есть поле — форма строгая (blocking), пустое — снять поле;
    - `confidence_basis` — что снижает уверенность вердикта: строка или null; незаполненный TODO_LLM
      из стаба — blocking; при advisor_verdict_confidence < 0,8 без причины — warning (старые обзоры
      поля не несут, блокировать их пересохранение незачем)."""
    wn = entry.get("week_note")
    if wn is not None:
        p = f"{path}.week_note"
        if not isinstance(wn, dict):
            issues.append({"field": p, "severity": "blocking",
                           "expected": "dict {what_happened: [str], recommendation: [str]|null, macro_link: str|null}",
                           "actual": wn if _is_todo_llm(wn) else type(wn).__name__})
        else:
            unknown = set(wn) - _WEEK_NOTE_KEYS
            if unknown:
                issues.append({"field": p, "severity": "blocking",
                               "expected": "только what_happened, recommendation, macro_link",
                               "actual": f"лишние ключи: {sorted(unknown)}"})
            for k in ("what_happened", "recommendation"):
                v = wn.get(k)
                if v is None and k == "recommendation":
                    continue
                if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                    issues.append({"field": f"{p}.{k}", "severity": "blocking",
                                   "expected": "список непустых строк", "actual": str(v)[:80]})
                elif any(_is_todo_llm(x) for x in v):
                    issues.append({"field": f"{p}.{k}", "severity": "blocking",
                                   "expected": "replaced TODO_LLM placeholder", "actual": "TODO_LLM в пунктах"})
            ml = wn.get("macro_link")
            if ml is not None and (not isinstance(ml, str) or not ml.strip() or _is_todo_llm(ml)):
                issues.append({"field": f"{p}.macro_link", "severity": "blocking",
                               "expected": "непустая строка или null", "actual": str(ml)[:80]})
            if not wn.get("what_happened") and not wn.get("recommendation"):
                issues.append({"field": p, "severity": "blocking",
                               "expected": "хотя бы один пункт в what_happened или recommendation (иначе снять поле)",
                               "actual": "пусто"})
    if "confidence_basis" in entry:
        v = entry["confidence_basis"]
        if _is_todo_llm(v):
            issues.append({"field": f"{path}.confidence_basis", "severity": "blocking",
                           "expected": "replaced TODO_LLM placeholder: что снижает уверенность (одна фраза) или null",
                           "actual": v})
        elif v is not None and (not isinstance(v, str) or not v.strip()):
            issues.append({"field": f"{path}.confidence_basis", "severity": "blocking",
                           "expected": "непустая строка или null", "actual": str(v)[:80]})
    conf = entry.get("advisor_verdict_confidence")
    if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < CONFIDENCE_BASIS_FROM:
        v = entry.get("confidence_basis")
        if not (isinstance(v, str) and v.strip()) or _is_todo_llm(v):
            issues.append({"field": f"{path}.confidence_basis", "severity": "warning",
                           "expected": f"что снижает уверенность (advisor_verdict_confidence {conf} < {CONFIDENCE_BASIS_FROM})",
                           "actual": "missing"})


def _check_required_field(
    obj: dict,
    parent_path: str,
    field: str,
    issues: list,
    *,
    expected_type: type | tuple | None = None,
    allowed_values: set | None = None,
    allow_null: bool = False,
) -> None:
    """Универсальный чек: поле присутствует + не TODO_LLM + правильного типа + в enum."""
    path = f"{parent_path}.{field}" if parent_path else field
    if field not in obj:
        issues.append({
            "field": path,
            "severity": "blocking",
            "expected": "present",
            "actual": "missing",
        })
        return
    v = obj[field]
    if _is_todo_llm(v):
        issues.append({
            "field": path,
            "severity": "blocking",
            "expected": "replaced TODO_LLM placeholder with actual value",
            "actual": v,
        })
        return
    if v is None:
        if not allow_null:
            issues.append({
                "field": path,
                "severity": "blocking",
                "expected": "non-null value",
                "actual": None,
            })
        return
    if expected_type is not None:
        # Note: bool is subclass of int — explicit check first
        if expected_type is float and isinstance(v, bool):
            issues.append({
                "field": path,
                "severity": "blocking",
                "expected": "float/number",
                "actual": f"bool: {v}",
            })
            return
        if not isinstance(v, expected_type):
            issues.append({
                "field": path,
                "severity": "blocking",
                "expected": f"type {expected_type}",
                "actual": f"{type(v).__name__}: {v!r}"[:80],
            })
            return
    if allowed_values is not None and v not in allowed_values:
        issues.append({
            "field": path,
            "severity": "blocking",
            "expected": f"one of {sorted(allowed_values)}",
            "actual": str(v),
        })


def _check_drift_renames(
    entry: dict,
    parent_path: str,
    drift_map: dict,
    issues: list,
) -> None:
    """Проверка: запрещённые drift-имена в entry → blocking."""
    for drift_name, canonical in drift_map.items():
        if drift_name in entry:
            issues.append({
                "field": f"{parent_path}.{drift_name}",
                "severity": "blocking",
                "expected": f"canonical field name: '{canonical}'",
                "actual": f"drift-rename '{drift_name}' (used by Opus gen 2026-05-12)",
            })


# ── Phase 4 (schema v2): горизонты + date_window (§11.3) ──

_DW_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)
# Разделитель диапазона: '..', em/en-dash, ' - ' (с пробелами), ' to '. Дефис без
# пробелов НЕ считается разделителем (иначе ломает YYYY-MM-DD / YYYY-MM).
_DW_RANGE_SEP_RE = re.compile(r"(?:\s*\.\.\s*|\s*[—–]\s*|\s+-\s+|\s+to\s+)", re.IGNORECASE)
# v1-поля горизонта, запрещённые в v2-файле (анти-möbius drift)
V1_HORIZON_FIELDS = ("horizon_months", "horizon_end", "horizon")


def _parse_one_date_token(tok: str) -> date | None:
    tok = (tok or "").strip()
    if not tok:
        return None
    m = _DW_QUARTER_RE.match(tok)              # YYYY-Qn → 1-е число первого месяца квартала
    if m:
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", tok):  # YYYY-MM-DD
        try:
            return date.fromisoformat(tok)
        except ValueError:
            return None
    if re.match(r"^\d{4}-\d{2}$", tok):        # YYYY-MM → 1-е число
        y, mo = int(tok[:4]), int(tok[5:7])
        return date(y, mo, 1) if 1 <= mo <= 12 else None
    if re.match(r"^\d{4}$", tok):              # YYYY → 1 января
        return date(int(tok), 1, 1)
    return None


def _parse_date_window_start(s: str) -> date | None:
    """Начало окна date_window по контракту §11.3. None если непарсибельно."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    left = _DW_RANGE_SEP_RE.split(s)[0].strip()  # диапазон → левая сторона
    return _parse_one_date_token(left)


def _add_months_eom(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _validate_horizons_block(data: dict, issues: list) -> None:
    """v2: horizons (sorted unique ints), horizon_ends (ключи hNN ровно по horizons,
    даты ISO + согласованы с базой), primary_horizon ∈ horizons.
    horizon_mode: rolling (default) — base+N мес, конец месяца, ±5д;
                  anchored          — фиксированные даты, метка hNN — конвенция: ±ANCHORED_TOL_MONTHS мес, строго возрастают.
    Якорь: для stress (type=portfolio-stress-test) → поле `date`;
           для остальных (weekly-review) → поле `review_date`."""
    horizons = data.get("horizons")
    if not isinstance(horizons, list) or not horizons:
        issues.append({"field": "horizons", "severity": "blocking",
                       "expected": "непустой список месяцев [int]", "actual": str(horizons)})
        horizons = None
    elif any(not isinstance(h, int) or isinstance(h, bool) for h in horizons):
        issues.append({"field": "horizons", "severity": "blocking",
                       "expected": "список целых чисел", "actual": str(horizons)})
        horizons = None
    elif sorted(set(horizons)) != list(horizons):
        issues.append({"field": "horizons", "severity": "blocking",
                       "expected": "отсортированный список уникальных int", "actual": str(horizons)})

    primary = data.get("primary_horizon")
    if horizons and (primary not in horizons):
        issues.append({"field": "primary_horizon", "severity": "blocking",
                       "expected": f"один из horizons {sorted(set(horizons))}", "actual": str(primary)})

    h_ends = data.get("horizon_ends")
    if not isinstance(h_ends, dict):
        issues.append({"field": "horizon_ends", "severity": "blocking",
                       "expected": "dict {hNN: 'YYYY-MM-DD'}", "actual": str(h_ends)})
        return
    if horizons:
        expected_keys = {f"h{h}" for h in horizons}
        if set(h_ends) != expected_keys:
            issues.append({"field": "horizon_ends", "severity": "blocking",
                           "expected": f"ключи ровно {sorted(expected_keys)}",
                           "actual": str(sorted(h_ends))})

    # Якорь: stress использует `date` (дата прогона), weekly-review — `review_date`.
    # Нельзя брать `review_date or date`: у stress review_date = дата следующего ревью (+6мес).
    is_stress = data.get("type") == "portfolio-stress-test"
    anchor_field = "date" if is_stress else "review_date"
    base_raw = data.get(anchor_field) or data.get("date")
    base = _parse_one_date_token(str(base_raw)[:10]) if base_raw else None

    # horizon_mode: rolling (default) или anchored
    horizon_mode = data.get("horizon_mode", "rolling")
    if horizon_mode not in ("rolling", "anchored"):
        issues.append({"field": "horizon_mode", "severity": "warning",
                       "expected": "rolling | anchored (default: rolling)",
                       "actual": str(horizon_mode)})
        horizon_mode = "rolling"

    if base and horizons:
        dates_by_h: dict = {}
        for h in horizons:
            v = h_ends.get(f"h{h}")
            d = _parse_one_date_token(str(v)[:10]) if v else None
            if d is None:
                issues.append({"field": f"horizon_ends.h{h}", "severity": "blocking",
                               "expected": "дата ISO YYYY-MM-DD", "actual": str(v)})
                continue
            dates_by_h[h] = d
            if horizon_mode == "rolling":
                exp = _add_months_eom(base, h)
                if abs((d - exp).days) > 5:
                    issues.append({
                        "field": f"horizon_ends.h{h}", "severity": "warning",
                        "expected": (f"≈ {exp.isoformat()} "
                                     f"(mode=rolling, якорь={anchor_field}+{h}мес, конец месяца, ±5д)"),
                        "actual": d.isoformat(),
                    })
            else:  # anchored
                if d <= base:
                    issues.append({
                        "field": f"horizon_ends.h{h}", "severity": "blocking",
                        "expected": f"дата > {anchor_field}={base.isoformat()} (mode=anchored)",
                        "actual": d.isoformat(),
                    })
                else:
                    actual_months = (d.year - base.year) * 12 + (d.month - base.month)
                    if abs(actual_months - h) > ANCHORED_TOL_MONTHS:
                        issues.append({
                            "field": f"horizon_ends.h{h}", "severity": "warning",
                            "expected": (f"≈ {h} мес от {anchor_field}={base.isoformat()} "
                                         f"(mode=anchored, ±{ANCHORED_TOL_MONTHS}мес); фактически {actual_months} мес"),
                            "actual": d.isoformat(),
                        })
        # anchored: horizon_ends должны строго возрастать
        if horizon_mode == "anchored" and len(dates_by_h) > 1:
            for h1, h2 in zip(sorted(dates_by_h)[:-1], sorted(dates_by_h)[1:]):
                if dates_by_h[h1] >= dates_by_h[h2]:
                    issues.append({
                        "field": "horizon_ends", "severity": "blocking",
                        "expected": f"h{h1} < h{h2} по дате (mode=anchored, даты строго возрастают)",
                        "actual": f"{dates_by_h[h1].isoformat()} >= {dates_by_h[h2].isoformat()}",
                    })


def _check_v1_horizon_fields_in_v2(data: dict, issues: list) -> None:
    """v2: присутствие любого v1-поля горизонта на top-level → blocking v1_field_in_v2."""
    for f in V1_HORIZON_FIELDS:
        if f in data:
            issues.append({"field": f, "severity": "blocking",
                           "expected": "поле удалено в v2 (см. §11.4)",
                           "actual": f"v1_field_in_v2: '{f}' присутствует"})


def _validate_catalyst(cat: dict, path: str, issues: list, *, v2: bool = False) -> None:
    """Структурная проверка одной записи catalyst[i] с поддержкой kind v2 (METH-1).

    `kind: binary` → требует p ∈ (0,0.95], upside_pct + upside_ci_pct (или downside_*).
    `kind: quantitative` → требует upside_by_scenario с 4 ID, без поля p.
    `kind` отсутствует → warning (legacy), затем legacy-валидация (p+upside_pct).

    v2 (schema v2): поле `in_horizon` удалено — НЕ требуется; его присутствие →
    blocking `v1_field_in_v2`. Принадлежность горизонту считает consumer из
    `date_window` (контракт §11.3), поэтому date_window валидируется на парсибельность.
    """
    if not isinstance(cat, dict):
        issues.append({
            "field": path,
            "severity": "blocking",
            "expected": "dict with catalyst fields",
            "actual": str(type(cat).__name__),
        })
        return

    # Required across both kinds
    for field in ("id", "trigger", "date_window", "source", "source_quality"):
        _check_required_field(cat, path, field, issues, expected_type=str)
    if v2:
        # in_horizon удалён в v2 — присутствие = drift
        if "in_horizon" in cat:
            issues.append({
                "field": f"{path}.in_horizon",
                "severity": "blocking",
                "expected": "поле удалено в v2 (consumer вычисляет из date_window)",
                "actual": "v1_field_in_v2: 'in_horizon' присутствует",
            })
        # date_window должен парситься контрактом §11.3 (warning, не blocking)
        dw = cat.get("date_window")
        if isinstance(dw, str) and not _is_todo_llm(dw) and _parse_date_window_start(dw) is None:
            issues.append({
                "field": f"{path}.date_window",
                "severity": "warning",
                "expected": "парсибельный по §11.3 (YYYY-MM | YYYY-MM-DD | YYYY | YYYY-Qn | диапазон)",
                "actual": f"date_window_unparseable: {dw!r} (catalyst попадёт во все горизонты)",
            })
    else:
        _check_required_field(cat, path, "in_horizon", issues, expected_type=bool)

    sq = cat.get("source_quality")
    if isinstance(sq, str) and not _is_todo_llm(sq) and sq not in VALID_LEVEL_HML:
        issues.append({
            "field": f"{path}.source_quality",
            "severity": "blocking",
            "expected": "HIGH | MEDIUM | LOW",
            "actual": sq,
        })

    # R11 (2026-08-16): атрибуция источника для матрицы доверия. Переходный режим —
    # warning, а не blocking: обзоры до этой даты поля не несут, и блокировать их
    # сохранение незачем. Проверяется ФОРМА; словарь имён — в INDEX.md, здесь его нет.
    # Пустой/битый тег хуже отсутствующего: он выглядит атрибуцией, не будучи ею,
    # и потребитель посчитает такой катализатор проверенным фильтром.
    st = cat.get("source_trust")
    if st is not None:
        if not isinstance(st, dict):
            issues.append({
                "field": f"{path}.source_trust",
                "severity": "blocking",
                "expected": "dict {analyst, subdomain}",
                "actual": f"source_trust_not_dict: {type(st).__name__}",
            })
        else:
            missing = [k for k in ("analyst", "subdomain")
                       if not isinstance(st.get(k), str) or not st.get(k, "").strip()
                       or _is_todo_llm(st.get(k, ""))]
            if missing:
                issues.append({
                    "field": f"{path}.source_trust",
                    "severity": "blocking",
                    "expected": "непустые строки analyst и subdomain",
                    "actual": f"source_trust_incomplete: {missing}",
                })

    raw_kind = cat.get("kind")
    kind: str | None
    if raw_kind is None:
        kind = None
    else:
        kind_s = str(raw_kind).strip().lower()
        if kind_s in ("binary", "quantitative"):
            kind = kind_s
        else:
            issues.append({
                "field": f"{path}.kind",
                "severity": "blocking",
                "expected": "'binary' or 'quantitative' (METH-1)",
                "actual": str(raw_kind),
            })
            return

    if kind is None:
        # Legacy без kind — warning + fallback legacy валидация
        issues.append({
            "field": f"{path}.kind",
            "severity": "warning",
            "expected": "'binary' or 'quantitative' (METH-1, рекомендуется явный kind)",
            "actual": "missing — backward-compat принимаем legacy schema, "
                      "но aggregator занижает quant-катализаторы при scenario gate",
        })
        # Эвристика: если есть upside_by_scenario → проверять как quant; иначе как legacy binary
        if "upside_by_scenario" in cat:
            _validate_catalyst_quantitative(cat, path, issues)
        else:
            _validate_catalyst_binary(cat, path, issues)
    elif kind == "binary":
        _validate_catalyst_binary(cat, path, issues)
    elif kind == "quantitative":
        _validate_catalyst_quantitative(cat, path, issues)


def _validate_catalyst_binary(cat: dict, path: str, issues: list) -> None:
    """Binary catalyst: p + upside/downside + (опц.) active_scenarios или macro_dependency."""
    _check_required_field(cat, path, "p", issues, expected_type=(int, float))
    p_val = cat.get("p")
    if isinstance(p_val, (int, float)) and not isinstance(p_val, bool):
        if not (0 <= p_val <= 1):
            issues.append({
                "field": f"{path}.p",
                "severity": "blocking",
                "expected": "0 ≤ p ≤ 1",
                "actual": str(p_val),
            })
        elif p_val > 0.95:
            issues.append({
                "field": f"{path}.p",
                "severity": "warning",
                "expected": "p ≤ 0.95 (METH-1 рекомендация: всегда оставлять uncertainty)",
                "actual": str(p_val),
            })

    md = cat.get("macro_dependency")
    if _is_todo_llm(md):
        issues.append({
            "field": f"{path}.macro_dependency",
            "severity": "blocking",
            "expected": "scenario_id (A/B/C/D) or null",
            "actual": md,
        })

    has_upside = cat.get("upside_pct") is not None and not _is_todo_llm(cat.get("upside_pct"))
    has_downside = cat.get("downside_pct") is not None and not _is_todo_llm(cat.get("downside_pct"))
    if not (has_upside or has_downside):
        issues.append({
            "field": f"{path}.upside_pct/downside_pct",
            "severity": "blocking",
            "expected": "at least one of upside_pct/downside_pct (numeric, not TODO_LLM)",
            "actual": "both missing/null/TODO",
        })
    for side, side_ci in (("upside_pct", "upside_ci_pct"), ("downside_pct", "downside_ci_pct")):
        val = cat.get(side)
        ci = cat.get(side_ci)
        if val is not None and not _is_todo_llm(val):
            if ci is None or _is_todo_llm(ci) or not isinstance(ci, list) or len(ci) != 2:
                issues.append({
                    "field": f"{path}.{side_ci}",
                    "severity": "blocking",
                    "expected": f"[lo, hi] list (since {side}={val})",
                    "actual": str(ci),
                })


_VALID_SCENARIO_IDS = {"A", "B", "C", "D", "Sc-A", "Sc-B", "Sc-C", "Sc-D"}


def _validate_catalyst_quantitative(cat: dict, path: str, issues: list) -> None:
    """Quantitative catalyst: upside_by_scenario (4 IDs) + upside_ci_by_scenario; без p."""
    # p НЕ должно присутствовать (warning)
    if cat.get("p") is not None:
        issues.append({
            "field": f"{path}.p",
            "severity": "warning",
            "expected": "absent (quantitative: uncertainty в CI, не в p)",
            "actual": str(cat.get("p")),
        })
    ubs = cat.get("upside_by_scenario")
    if not ubs or not isinstance(ubs, dict):
        issues.append({
            "field": f"{path}.upside_by_scenario",
            "severity": "blocking",
            "expected": "dict {A: num, B: num, C: num, D: num}",
            "actual": str(ubs),
        })
        return
    # Проверяем ключи на валидность и значения на TODO_LLM/numeric
    for k, v in ubs.items():
        if k not in _VALID_SCENARIO_IDS:
            issues.append({
                "field": f"{path}.upside_by_scenario.{k}",
                "severity": "blocking",
                "expected": f"scenario_id из {sorted(_VALID_SCENARIO_IDS)}",
                "actual": k,
            })
        if _is_todo_llm(v):
            issues.append({
                "field": f"{path}.upside_by_scenario.{k}",
                "severity": "blocking",
                "expected": "numeric value",
                "actual": str(v),
            })
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            issues.append({
                "field": f"{path}.upside_by_scenario.{k}",
                "severity": "blocking",
                "expected": "numeric value",
                "actual": f"{type(v).__name__}: {v!r}",
            })
    # CI — recommended (warning если нет)
    ucbs = cat.get("upside_ci_by_scenario")
    if not ucbs:
        issues.append({
            "field": f"{path}.upside_ci_by_scenario",
            "severity": "warning",
            "expected": "dict {A: [lo, hi], B: [lo, hi], ...}",
            "actual": "missing (рекомендуется ±50% или ±100% если нет analogue)",
        })
    elif isinstance(ucbs, dict):
        for k, ci in ucbs.items():
            if not isinstance(ci, list) or len(ci) != 2:
                issues.append({
                    "field": f"{path}.upside_ci_by_scenario.{k}",
                    "severity": "blocking",
                    "expected": "[lo, hi] list",
                    "actual": str(ci),
                })


def _validate_user_constraints(entry: dict, path: str, issues: list, data: dict | None = None) -> None:
    """Срез ограничений бумаги `user_constraints[]` (schema.md §4.2; Workflow F2.6).

    Срез производный: строит его `reconcile_constraints.py` советника из условий (модуль (а)) и плана владельца,
    код его как источник не читает. Проверяется только форма — общим правилом
    `constraint_engine.slice_form_errors`:
      - обзор новой формы (`recorded_at`, а без него `review_date`, не раньше SLICE_SINCE): запись с `derived`
        обязана иметь `derived: true`, `as_of`, ровно одно из `condition_id` / `plan_field`, `summary` — иначе
        blocking; запись без `derived` (прежняя форма «ограничения обзора») — warning «устаревшая форма,
        игнорируется»;
      - старые обзоры — без проверок формы;
      - TRIPLET RULE (форма, обе эпохи): `unconstrained_verdict` ≠ `advisor_verdict` ⇒ срез непуст (в новой
        форме — хотя бы одна запись с `derived`), иначе blocking.
    """
    constraints = entry.get("user_constraints")
    uv = entry.get("unconstrained_verdict")
    av = entry.get("advisor_verdict")
    ce = _load_constraint_engine()
    new_era = bool(ce and ce.slice_era(data or {}))

    derived = [c for c in constraints if ce and ce.is_derived(c)] if isinstance(constraints, list) else []
    if uv and av and uv != av and not (derived if new_era else constraints):
        issues.append({
            "field": f"{path}.user_constraints",
            "severity": "blocking",
            "expected": "непустой срез user_constraints[] (unconstrained_verdict ≠ advisor_verdict — "
                        "вердикт изменило условие или план; срез строит reconcile_constraints.py)",
            "actual": "срез пуст (TRIPLET RULE)",
        })
    if constraints is None or not new_era:
        return
    if ce is None:
        issues.append({"field": f"{path}.user_constraints", "severity": "warning",
                       "expected": "constraint_engine импортируем для проверки формы среза",
                       "actual": "import failed (не найден ни в scripts/, ни в _shared-references/)"})
        return
    for err in ce.slice_form_errors(constraints):
        issues.append({"field": f"{path}.{err.split(':', 1)[0]}", "severity": "blocking",
                       "expected": "срез: derived: true, as_of, condition_id | plan_field, summary (schema.md §4.2)",
                       "actual": err})
    if isinstance(constraints, list):
        for idx, c in enumerate(constraints):
            if isinstance(c, dict) and not ce.is_derived(c):
                issues.append({"field": f"{path}.user_constraints[{idx}]", "severity": "warning",
                               "expected": "запись среза с derived: true (reconcile_constraints.py)",
                               "actual": "устаревшая форма «ограничения обзора», игнорируется — ограничение "
                                         "заводится условием (Режим 9) или словом плана"})


def _load_constraint_engine():
    """Импорт общего движка `constraint_engine` (канон в _shared-references/).

    Из репо берётся из `_shared-references/`; в упакованном .skill — из своей `scripts/`
    (туда его кладёт pack.sh из _shared-references, и Python сам добавляет каталог
    скрипта в sys.path). Возвращает модуль или None, если недоступен.
    """
    import os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    for _cand in (_here, _os.path.normpath(_os.path.join(_here, "..", "..", "..", "_shared-references"))):
        if _cand not in sys.path:
            sys.path.insert(0, _cand)
    try:
        import constraint_engine
        return constraint_engine
    except ImportError:
        return None


def _expected_priority(entry: dict, ctx: dict):
    """verification_priority бумаги по движку (constraint_engine.compute_verification_priority) в контексте
    тикера {gate_status, active_condition_verdicts}; движка нет — None."""
    constraint_engine = _load_constraint_engine()
    if constraint_engine is None:
        return None
    return constraint_engine.compute_verification_priority(
        entry,
        active_condition_verdicts=ctx.get("active_condition_verdicts"),
        gate_status=ctx.get("gate_status"),
        has_hidden_critical_event=bool(ctx.get("has_hidden_critical_event", False)),
    )


def _priority_check(entry: dict, path: str, ctx: dict | None, issues: list) -> None:
    """Part C (verification_priority — derived, R28): приоритет ставит `stamp-report` функцией движка
    (constraint_engine.compute_verification_priority), модель поле не заполняет и прошлое значение не переносится.

    С контекстом тикера `data._priority_context[ticker] = {gate_status, active_condition_verdicts}` (его строит
    `_priority_context_from_root` при `--root <корень Claude-Memory>`: гейт — модуль (б) `last_word` по решениям
    ключа и строке самого обзора (`flags.gate_review_required`, если у обзора есть `recorded_at`), справочник бумаг
    корня — для IPO-паузы; условия — действующие строки модуля (а) на `review_date`; копия `gate_status_snapshot`
    обзора не читается) пустое поле или расхождение с движком — BLOCKING: запустить `stamp-report`.
    Без контекста — пропуск (сводное предупреждение «контекст не передан» даёт `_priority_stamp_check`).
    """
    if not ctx:
        return
    expected = _expected_priority(entry, ctx)
    if expected is None:
        return
    stored = entry.get("verification_priority")
    if not isinstance(stored, str) or stored.upper() != expected:
        issues.append({
            "field": f"{path}.verification_priority",
            "severity": "blocking",
            "expected": f"{expected} — приоритет ставит stamp-report (движок: вердикт, уверенность, условия, гейт)",
            "actual": f"{stored} — не проставлен или не пересчитан: запусти assemble_artifact.py stamp-report "
                      f"--root <корень> --doc Portfolio/weekly-reviews/<файл>.yaml",
        })


# Обзоры с recorded_at (без него — review_date) не раньше этой даты штампуются stamp-report (R28): приоритет без
# сверки (нет --root) — предупреждение «контекст не передан».
STRESS_UNMAPPED_SINCE = "2026-11-06"   # стрессы с этой даты: непустой unmapped_tickers — блок (решение владельца 06.11)
PRIORITY_STAMP_SINCE = "2026-11-03"


def _priority_stamp_check(data: dict, items_key: str, issues: list) -> None:
    """Сводные предупреждения обзора по R28: (1) копия `gate_status_snapshot` у бумаг — устаревшее поле, вьюер и
    скрипты его не читают (старые обзоры валидны); (2) без `--root` приоритет не сверен — «контекст не передан»
    (пустые поля и новые обзоры)."""
    items = data.get(items_key) if isinstance(data.get(items_key), dict) else {}
    snap = sorted(k for k, e in items.items() if isinstance(e, dict) and "gate_status_snapshot" in e)
    if snap:
        issues.append({
            "field": f"{items_key}.*.gate_status_snapshot",
            "severity": "warning",
            "expected": "поля нет: статус гейта — только модуль (б) (выборка security_digest), копия в обзоре не читается",
            "actual": f"устаревшая копия у {len(snap)} бумаг ({', '.join(snap[:5])}{' …' if len(snap) > 5 else ''})",
        })
    if data.get("_priority_context") is not None:
        return
    empty = sorted(k for k, e in items.items() if isinstance(e, dict) and e.get("verification_priority") is None)
    when = str(data.get("recorded_at") or data.get("review_date") or "")[:10]
    if empty or when >= PRIORITY_STAMP_SINCE:
        issues.append({
            "field": f"{items_key}.*.verification_priority",
            "severity": "warning",
            "expected": "приоритет проставлен stamp-report и сверен с решениями и условиями (--root)",
            "actual": "контекст не передан: приоритет не сверен"
                      + (f"; пустой у {len(empty)} бумаг — запусти stamp-report --root" if empty else ""),
        })


# Обзоры не раньше этой даты (review_date) — новая структура: упразднённые блоки и пункты проверки при «срочно»
# проверяются; старые обзоры — без замечаний.
NEW_REVIEW_SINCE = "2026-10-31"
# Упразднённые блоки старого формата (03.11): состояние условий пишет только сайт (conditions-state.json),
# гейт — модуль (б); обзор их не несёт (перенос carry_over_weekly их не берёт).
OBSOLETE_REVIEW_BLOCKS = ("conditions_evaluated", "gate_review_directives", "proposed_gate_review_directives",
                          "conditions_state", "conditions_mutations_applied")


def _obsolete_blocks_check(data: dict, issues: list) -> None:
    """Упразднённые блоки в новом обзоре: любой — warning; `conditions_evaluated.written_back: true` — blocking
    («обзор не пишет состояние условий»). review_date < NEW_REVIEW_SINCE — без замечаний."""
    if str(data.get("review_date") or "")[:10] < NEW_REVIEW_SINCE:
        return
    for k in OBSOLETE_REVIEW_BLOCKS:
        if k in data:
            issues.append({"field": k, "severity": "warning",
                           "expected": "блока нет: упразднённый блок старого формата; состояние условий пишет только сайт",
                           "actual": "блок есть — убрать из YAML (резолюция сработавшего условия — фрагмент "
                                     "<!-- cond: id --> в changes.md)"})
    ce = data.get("conditions_evaluated")
    if isinstance(ce, dict) and ce.get("written_back") is True:
        issues.append({"field": "conditions_evaluated.written_back", "severity": "blocking",
                       "expected": "обзор не пишет состояние условий (только сайт: кнопки владельца, уведомитель)",
                       "actual": "written_back: true — утверждение о записи, которой не было; блок убрать"})


def _checklist_check(data: dict, items_key: str, issues: list) -> None:
    """Пункты проверки обязательны при «срочно» (03.11): по приоритету после штампа (с контекстом --root — функцией
    движка, иначе записанный) HIGH без непустого `verification_checklist` — blocking, MEDIUM — warning, LOW — ничего.
    Исключение: HIGH не от вердикта-действия, а от гейта «нужен разбор» (review_needed / review_aging / new_position;
    без контекста — вердикт не действие) — warning «нужен разбор: «Разбери X»». Обзоры до NEW_REVIEW_SINCE — без
    замечаний."""
    if str(data.get("review_date") or "")[:10] < NEW_REVIEW_SINCE:
        return
    items = data.get(items_key) if isinstance(data.get(items_key), dict) else {}
    ctx_all = data.get("_priority_context")
    engine = _load_constraint_engine()
    for key, e in items.items():
        if not isinstance(e, dict):
            continue
        ctx = (ctx_all or {}).get(key) if ctx_all is not None else None
        prio = _expected_priority(e, ctx) if ctx is not None else None
        if prio is None:
            prio = str(e.get("verification_priority") or "").upper()
        cl = e.get("verification_checklist")
        if isinstance(cl, list) and any((str(x).strip() if not isinstance(x, dict) else x) for x in cl):
            continue
        path = f"{items_key}.{key}.verification_checklist"
        if prio == "HIGH":
            actionable = engine is not None and str(e.get("advisor_verdict") or "").upper() in engine.ACTIONABLE_VERDICTS
            pending = engine.GATE_REVIEW_PENDING if engine is not None else set()
            by_gate = not actionable and (ctx is None or (ctx or {}).get("gate_status") in pending)
            if by_gate:
                issues.append({"field": path, "severity": "warning",
                               "expected": f"нужен разбор: «Разбери {key}» (срочность — от гейта, пункты проверки не нужны)",
                               "actual": "«срочно» без пунктов проверки"})
            else:
                issues.append({"field": path, "severity": "blocking",
                               "expected": "1–3 пункта: проверяемое утверждение с датой или порогом, без прозы",
                               "actual": "«срочно» (HIGH) без пунктов проверки — «Проверить» на сайте пуст"})
        elif prio == "MEDIUM":
            issues.append({"field": path, "severity": "warning",
                           "expected": "1–3 пункта проверки при «желательно» (MEDIUM)",
                           "actual": "пунктов нет"})


def _validate_dividend_forward(
    entry: dict, path: str, issues: list, review_date=None,
) -> None:
    """Слой 3 total-return: опциональный блок dividend_forward (back-compat:
    отсутствие блока валидно). Если присутствует:
    - policy_state обязателен, enum VALID_DIV_POLICY_STATE;
    - declared/expected → year1_yield_pct (число), year2_basis (enum),
      year2_yield_pct (число, если basis != none), source/as_of/confidence;
    - suspended/none/uncertain → year*_yield_pct НЕ должны нести ненулевой yield
      (вклад строго 0, «не оживает»); uncertain без note → warning (пропуск
      должен читаться как ПРОПУСК, не как «дивы = 0»);
    - year2_basis carry_forward + confidence HIGH → warning (carry_forward = LOW);
    - as_of старше DIV_FORWARD_STALE_DAYS от review_date → warning stale.
    """
    df = entry.get("dividend_forward")
    if df is None:
        return
    p = f"{path}.dividend_forward"
    if _is_todo_llm(df) or not isinstance(df, dict):
        issues.append({
            "field": p, "severity": "blocking",
            "expected": "dict {policy_state, year1_yield_pct, ...}",
            "actual": df if _is_todo_llm(df) else type(df).__name__,
        })
        return

    # Незаменённые TODO_LLM в любом поле блока → blocking (в т.ч. в полях,
    # которые для данного policy_state полагалось УДАЛИТЬ, а не оставить).
    todo_fields = [k for k, v in df.items() if _is_todo_llm(v)]
    if todo_fields:
        for k in todo_fields:
            issues.append({
                "field": f"{p}.{k}", "severity": "blocking",
                "expected": "replaced TODO_LLM placeholder (или удалить поле)",
                "actual": df[k],
            })
        return

    _check_required_field(df, p, "policy_state", issues,
                          expected_type=str, allowed_values=VALID_DIV_POLICY_STATE)
    ps = df.get("policy_state")
    contributing = ps in ("declared", "expected")

    if contributing:
        _check_required_field(df, p, "year1_yield_pct", issues,
                              expected_type=(int, float))
        _check_required_field(df, p, "year2_basis", issues,
                              expected_type=str, allowed_values=VALID_DIV_YEAR2_BASIS)
        if df.get("year2_basis") in ("analyst", "carry_forward"):
            _check_required_field(df, p, "year2_yield_pct", issues,
                                  expected_type=(int, float))
        _check_required_field(df, p, "source", issues, expected_type=str)
        _check_required_field(df, p, "confidence", issues,
                              expected_type=str, allowed_values=VALID_LEVEL_HML)
        _check_required_field(df, p, "as_of", issues, expected_type=str)
        if df.get("year2_basis") == "carry_forward" and df.get("confidence") == "HIGH":
            issues.append({
                "field": f"{p}.confidence", "severity": "warning",
                "expected": "carry_forward года 1 → LOW (никакого роста «с потолка»)",
                "actual": "HIGH при year2_basis: carry_forward",
            })
    else:
        # Гейт: не-contributing состояния не несут yield (вклад строго 0)
        for f in ("year1_yield_pct", "year2_yield_pct"):
            v = df.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                issues.append({
                    "field": f"{p}.{f}", "severity": "blocking",
                    "expected": f"отсутствие/0 при policy_state: {ps} (вклад = 0)",
                    "actual": str(v),
                })
        if ps == "uncertain" and not df.get("note"):
            issues.append({
                "field": f"{p}.note", "severity": "warning",
                "expected": "пометка «доход не учтён (политика неизвестна)» — "
                            "uncertain должен читаться как ПРОПУСК, не «дивы = 0»",
                "actual": "note отсутствует",
            })

    # Формат/свежесть as_of (если задан)
    as_of_raw = df.get("as_of")
    if isinstance(as_of_raw, str) and not _is_todo_llm(as_of_raw):
        as_of_d = None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", as_of_raw.strip()):
            try:
                as_of_d = date.fromisoformat(as_of_raw.strip())
            except ValueError:
                as_of_d = None
        if as_of_d is None:
            issues.append({
                "field": f"{p}.as_of", "severity": "blocking",
                "expected": "ISO-дата YYYY-MM-DD", "actual": as_of_raw,
            })
        else:
            rd = None
            if isinstance(review_date, str):
                try:
                    rd = date.fromisoformat(review_date.strip()[:10])
                except ValueError:
                    rd = None
            elif isinstance(review_date, date):
                rd = review_date
            if rd is not None and (rd - as_of_d).days > DIV_FORWARD_STALE_DAYS:
                issues.append({
                    "field": f"{p}.as_of", "severity": "warning",
                    "expected": f"не старше {DIV_FORWARD_STALE_DAYS} дн от review_date",
                    "actual": f"{as_of_raw} (stale: {(rd - as_of_d).days} дн) — "
                              f"понизить confidence / обновить проекцию",
                })


# RPA-34 (2026-10-26): сбор новостей по бумагам — субагентами через sweep_collect.py, не в основном
# контексте. 26.10.2026 обзор акций на Sonnet открыл ~45 страниц сам (fan-out в Mode 1 был лишь
# «рекомендован») и прошёл 3 компакции; новости после компакции пришлось искать в журнале сессии.
# Mode 2 обязателен с 20.10 (RPA-26), но проверки не было. Обзоры раньше даты не затрагиваются.
SWEEP_REQUIRED_FROM = "2026-10-27"
SWEEP_MIN_ITEMS = 5
SWEEP_METHODS = {"sweep_collect", "inline_owner_approved"}


def _sweep_method_check(data: dict, n_items: int, what: str, issues: list) -> None:
    """coverage.method = sweep_collect (или inline_owner_approved с причиной) при ≥5 бумагах."""
    rd = str(data.get("review_date") or "")[:10]
    if not rd or rd < SWEEP_REQUIRED_FROM or n_items < SWEEP_MIN_ITEMS:
        return
    cov = data.get("coverage")
    method = cov.get("method") if isinstance(cov, dict) else None
    if method not in SWEEP_METHODS:
        issues.append(_issue(
            "coverage.method", "blocking",
            f"sweep_collect (блок coverage из sweep_collect.py) при ≥{SWEEP_MIN_ITEMS} {what}; "
            "если субагентов в среде нет — inline_owner_approved + coverage.method_note "
            "(владелец согласился до сборки YAML)",
            str(method)))
    elif method == "inline_owner_approved":
        note = cov.get("method_note")
        if not isinstance(note, str) or not note.strip() or _is_todo_llm(note):
            issues.append(_issue("coverage.method_note", "blocking",
                                 "причина сбора без субагентов и когда владелец согласился", str(note)))
        else:
            issues.append(_issue("coverage.method", "warning",
                                 "sweep_collect", "inline_owner_approved — новости собраны в основном контексте"))


RESEARCH_FRESHNESS_DAYS = 7  # R-COV: окно свежести источников относительно review_date


def _research_freshness_check(entry: dict, path: str, review_date, issues: list) -> None:
    """R-COV (2026-07-23): детектор молчаливого carry-over per-stock блоков.

    Ретро-кейс: обзор 2026-07-23 у всех 21 тикеров нёс fundamental_score_sources
    с accessed_date 2026-07-11 и basis, побайтово идентичный обзору 15.07, — при
    заявлении в MD «проверено индивидуально все 21» (включая X5, у которого 16.07
    вышли операционные результаты Q2). Валидатор структуру видел полной и молчал.

    Правило: у тикера должен быть ≥1 источник (fundamental_score_sources или
    div_sources) с accessed_date в окне [review_date − RESEARCH_FRESHNESS_DAYS,
    review_date], ЛИБО явный флаг carried_over: true (осознанный перенос: новостей
    нет, фундаментальный блок от прошлой даты). Иначе — warning (не блок: перенос
    легален, нелегально лишь его замалчивание).
    """
    if not review_date:
        return
    if entry.get("carried_over") is True:
        return
    try:
        from datetime import date, timedelta
        rd = date.fromisoformat(str(review_date)[:10])
        floor = (rd - timedelta(days=RESEARCH_FRESHNESS_DAYS)).isoformat()
    except (ValueError, TypeError):
        return
    dates = []
    for key in ("fundamental_score_sources", "div_sources"):
        srcs = entry.get(key)
        if isinstance(srcs, list):
            for s in srcs:
                if isinstance(s, dict) and s.get("accessed_date"):
                    dates.append(str(s["accessed_date"])[:10])
    if any(d >= floor for d in dates):
        return
    issues.append({
        "field": f"{path}.fundamental_score_sources",
        "severity": "warning",
        "expected": (f"≥1 источник с accessed_date ≥ {floor} "
                     f"(окно {RESEARCH_FRESHNESS_DAYS} дн до review_date) "
                     "ИЛИ явный carried_over: true"),
        "actual": (f"свежих источников нет (max accessed_date: {max(dates) if dates else 'нет дат'}); "
                   "похоже на молчаливый carry-over блока из прошлого обзора"),
    })


_NUM = r"(\d{1,3}(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_STOCK_PRICE_IN_TEXT = re.compile(r"\bк\s+" + _NUM + r"\s*₽")
_BOND_PRICE_LEAD = re.compile(r"^\s*Цена\s+" + _NUM + r"\s*→\s*" + _NUM)


def _to_float(tok: str) -> float | None:
    try:
        return float(re.sub(r"[ \u00a0\u202f]", "", tok).replace(",", "."))
    except ValueError:
        return None


def _stale_text_check(entry: dict, path: str, kind: str, issues: list) -> None:
    """RPA-30 (аудит 20.10.2026, inc-2026-10-20-5): число обновлено, текст обоснования — нет.

    Акции: «X% к <цена> ₽» в div_basis / fundamental_score_basis при другой price_rub
    (SBER 16.10: «15,2% к 276,48 ₽» при цене 283,63 и поле 14,81). Облигации: вводная
    «Цена A → B» в advisor_verdict_basis, где B ≠ current_price. Только ценоподобные числа
    (в пределах ±40% от цены), расхождение > 0,5% у акций и > 0,15% у облигаций — warning, текст не правится.
    """
    if kind == "stock":
        price = entry.get("price_rub")
        fields = ("div_basis", "fundamental_score_basis", "advisor_verdict_basis")
    else:
        price = entry.get("current_price")
        fields = ("advisor_verdict_basis",)
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return
    for f in fields:
        text = entry.get(f)
        if not isinstance(text, str):
            continue
        if kind == "stock":
            vals = [_to_float(m.group(1)) for m in _STOCK_PRICE_IN_TEXT.finditer(text)]
        else:
            m = _BOND_PRICE_LEAD.match(text)
            vals = [_to_float(m.group(2))] if m else []
        for v in vals:
            if v is None or not (0.6 * price <= v <= 1.4 * price):
                continue
            # облигации в % номинала двигаются на десятые — порог строже, чем у акций
            if abs(v / price - 1) > (0.005 if kind == "stock" else 0.0015):
                issues.append({
                    "field": f"{path}.{f}",
                    "severity": "warning",
                    "expected": f"цена в тексте ≈ {price} (поле {'price_rub' if kind == 'stock' else 'current_price'})",
                    "actual": f"в тексте {v} — похоже, текст прошлой недели при обновлённых числах (RPA-30)",
                })
                break


def _catalyst_source_url_check(entry: dict, path: str, issues: list) -> None:
    """RPA-30: катализатор с внешним источником (source_trust.analyst ≠ advisor) без ссылки.

    Кейс 16.10.2026: CNRU cnru_9m_dividend_egm — «Эксперт/Ведомости 16.10», без url; сумма и
    даты независимо не подтвердились. Собственная оценка advisor ссылки не требует.
    """
    for idx, cat in enumerate(entry.get("catalyst") or []):
        if not isinstance(cat, dict):
            continue
        st = cat.get("source_trust") if isinstance(cat.get("source_trust"), dict) else {}
        if str(st.get("analyst", "")).lower() in ("advisor", "self", "", "moex_iss", "snapshot"):
            continue  # своя оценка или машинные данные (график выплат MOEX ISS, снапшот) — ссылка не нужна
        if "http" in str(cat.get("source") or ""):
            continue
        issues.append({
            "field": f"{path}.catalyst[{idx}].source",
            "severity": "warning",
            "expected": "url первоисточника для внешнего факта (или source_trust.analyst: advisor для своей оценки)",
            "actual": f"{cat.get('id')}: источник «{str(cat.get('source'))[:60]}» без ссылки (RPA-30)",
        })


SCENARIO_ATTRIBUTION_MIN_CATALYSTS = 10  # ниже порога сплошной null — warning, не блок


def _scenario_attribution_check(entries: dict, entries_key: str, issues: list) -> None:
    """Hard rule 4 (catalyst-tree-rules.md): сценарная привязка катализаторов.

    Ретро-кейс 2026-08-06 и 2026-08-15: во ВСЕХ катализаторах обоих обзоров
    (66 stock + 40 bond) `macro_dependency: null` при живой SSOT-матрице
    `scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml`. Валидатор проверял
    только тип отдельного поля и молчал, а portfolio-integrated-view считает
    joint expectation именно через macro_dependency — со сплошным null он
    деградирует молча.

    Привязанным считается катализатор с непустым `macro_dependency`, либо
    quantitative-катализатор с `upside_by_scenario` (там сценарии в структуре),
    либо с непустым `active_scenarios`. Частичный null легален: идиосинкратические
    триггеры (отчёт, отсечка, оферта) от сценария не зависят. Нелегален только
    сплошной — он означает, что привязка не делалась вовсе.
    """
    total = 0
    attributed = 0
    for entry in (entries or {}).values():
        if not isinstance(entry, dict):
            continue
        for cat in (entry.get("catalyst") or []):
            if not isinstance(cat, dict):
                continue
            total += 1
            md = cat.get("macro_dependency")
            has_md = md is not None and not _is_todo_llm(md) and md != []
            has_scn = isinstance(cat.get("upside_by_scenario"), dict) and bool(cat["upside_by_scenario"])
            has_act = bool(cat.get("active_scenarios"))
            if has_md or has_scn or has_act:
                attributed += 1
    if total == 0 or attributed > 0:
        return
    severity = "blocking" if total >= SCENARIO_ATTRIBUTION_MIN_CATALYSTS else "warning"
    issues.append({
        "field": f"{entries_key}[*].catalyst[*].macro_dependency",
        "severity": severity,
        "expected": ("≥1 катализатор со сценарной привязкой — scenario_id из активной "
                     "матрицы scenarios/ (Hard rule 4 catalyst-tree-rules.md). "
                     "«Стресс не собран» — не основание: матрица существует независимо"),
        "actual": (f"привязка отсутствует у всех {total} катализаторов — "
                   "portfolio-integrated-view не сможет посчитать joint expectation"),
    })


# AIR-1 D-3 (2026-10-07): явная вероятность у направленных вердиктов — проверяемое событие
# «позиция обгонит (направление up) или отстанет (down) от индекса класса/корзины за 3 мес.» (maps.verdict_direction).
# Без неё Брайер по advisor невозможен (advisor_verdict_confidence — не вероятность события).
P_OUTPERFORM_SINCE = "2026-10-08"      # обзоры раньше — без поля, только warning
_VERDICT_DIRECTION = codelists.map_("verdict_direction")
DIRECTIONAL_VERDICTS = {v for v, d in _VERDICT_DIRECTION.items() if d in ("up", "down")}


def _p_outperform_check(entry: dict, path: str, review_date, issues: list) -> None:
    """D-3: p_outperform_3m — число в [0, 1] у направленных вердиктов; у HOLD не нужно."""
    verdict = entry.get("unconstrained_verdict") or entry.get("advisor_verdict")
    p = entry.get("p_outperform_3m")
    if p is not None:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            issues.append({"field": f"{path}.p_outperform_3m", "severity": "blocking",
                           "expected": "число 0..1", "actual": repr(p)})
        return
    if verdict not in DIRECTIONAL_VERDICTS:
        return
    late = str(review_date or "")[:10] >= P_OUTPERFORM_SINCE
    issues.append({
        "field": f"{path}.p_outperform_3m",
        "severity": "blocking" if late else "warning",
        "expected": (f"вероятность 0..1 для {verdict}: позиция "
                     f"{'обгонит' if _VERDICT_DIRECTION.get(verdict) == 'up' else 'отстанет от'} "
                     "индекса класса/корзины за 3 мес. (AIR-1 D-3)"),
        "actual": "missing",
    })


def _trust_attribution_check(entries: dict, entries_key: str, issues: list) -> None:
    """R11 (trust-hierarchy.md): атрибуция источника катализаторов — `source_trust`.

    Зеркало сценарного гейта выше, для другой оси. Ретро-кейс 2026-08-15: матрица
    доверия из INDEX.md сопоставлялась потребителем с прозаическим полем `source`
    (URL или фраза) и не срабатывала НИ РАЗУ — 28 IGNORE-записей против 105
    катализаторов, 0 отфильтровано, при этом §9 отчёта мог бы написать
    «низкодоверенных источников нет» вместо «фильтр не работал».

    **Переходный режим: warning, не blocking.** Обзоры до 2026-08-16 поля не несут
    по построению, блокировать их пересохранение незачем. Ужесточать до blocking —
    когда обзоры начнут выходить с тегами (симметрично сценарному гейту).
    """
    total = 0
    tagged = 0
    for entry in (entries or {}).values():
        if not isinstance(entry, dict):
            continue
        for cat in (entry.get("catalyst") or []):
            if not isinstance(cat, dict):
                continue
            total += 1
            st = cat.get("source_trust")
            if (isinstance(st, dict)
                    and isinstance(st.get("analyst"), str) and st["analyst"].strip()
                    and isinstance(st.get("subdomain"), str) and st["subdomain"].strip()):
                tagged += 1
    if total == 0 or tagged > 0:
        return
    issues.append({
        "field": f"{entries_key}[*].catalyst[*].source_trust",
        "severity": "warning",
        "expected": ("атрибуция источника {analyst, subdomain} хотя бы у одного "
                     "катализатора (R11 trust-hierarchy.md); собственная оценка — "
                     "{advisor, self}, первичка — {issuer_disclosure, primary}"),
        "actual": (f"не атрибутирован ни один из {total} катализаторов — фильтр "
                   "матрицы доверия у portfolio-integrated-view применить не к чему; "
                   "отчёт обязан написать «фильтрация по доверию не работала», а не "
                   "«низкодоверенных источников нет»"),
    })


def validate_weekly_review_stock_detailed(data: dict) -> dict:
    """Детальная валидация weekly-review-stock YAML.

    Контракт: каноническая схема `weekly-stocks-review`, только schema_version 2
    (v1-приём снят V2-CUTOVER 2026-08-03; библиотека мигрирована wrap-as-single-horizon,
    мигратор: skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py).
    Блокирует если:
    - Top-level: schema_version != 2, type != "weekly-stocks-review",
      review_date/snapshot_id отсутствуют, горизонт-блок невалиден, per_stock пуст
    - На каждом ticker отсутствует / null / TODO_LLM / неверный тип у required-поля
    - Применено drift-имя (share_actual_pct, ie_share_pct, delta_pct, catalysts)
    - Присутствует v1-поле горизонта (horizon_months/horizon_end/in_horizon)
    - Структура catalyst[*] не полная (missing trigger/p/source/source_quality/CI)
    """
    issues: list[dict] = []
    v2 = (data.get("schema_version") == 2 and not isinstance(data.get("schema_version"), bool))

    # === Top-level ===
    if not v2:
        sv = data.get("schema_version")
        issues.append({
            "field": "schema_version",
            "severity": "blocking",
            "expected": "2 (integer; v1 снят V2-CUTOVER 2026-08-03 — "
                        "миграция: migrate_v1_to_v2.py)",
            "actual": f"{type(sv).__name__}: {sv!r}",
        })
    if data.get("type") != "weekly-stocks-review":
        issues.append({"field": "type", "severity": "blocking",
                       "expected": "'weekly-stocks-review'", "actual": str(data.get("type"))})
    for f in ("review_date", "snapshot_id"):
        if not data.get(f):
            issues.append({"field": f, "severity": "blocking",
                           "expected": "non-empty string", "actual": str(data.get(f))})
    _validate_horizons_block(data, issues)
    _check_v1_horizon_fields_in_v2(data, issues)

    # === per_stock ===
    per_stock = data.get("per_stock")
    if not per_stock or not isinstance(per_stock, dict):
        issues.append({
            "field": "per_stock",
            "severity": "blocking",
            "expected": "non-empty dict of {ticker: position}",
            "actual": str(type(per_stock).__name__) if per_stock else "missing/empty",
        })
    else:
        for ticker, entry in per_stock.items():
            path = f"per_stock.{ticker}"
            if not isinstance(entry, dict):
                issues.append({
                    "field": path,
                    "severity": "blocking",
                    "expected": "dict of fields",
                    "actual": str(type(entry).__name__),
                })
                continue
            # Anti-drift renames
            _check_drift_renames(entry, path, STOCK_DRIFT_FIELDS, issues)
            # Required deterministic fields (числа из snapshot)
            _check_required_field(entry, path, "sector", issues, expected_type=str)
            _check_required_field(entry, path, "weight_real_pct", issues, expected_type=(int, float))
            # RPA-19: плановая доля владельца — PRIMARY target; цель IE — secondary.
            _check_required_field(entry, path, "weight_user_planned_pct", issues,
                                  expected_type=(int, float), allow_null=True)
            _check_required_field(entry, path, "weight_ie_target_pct", issues,
                                  expected_type=(int, float), allow_null=True)
            _check_required_field(entry, path, "weight_divergence_vs_planned_pp", issues,
                                  expected_type=(int, float), allow_null=True)
            _check_required_field(entry, path, "weight_divergence_vs_ie_pp", issues,
                                  expected_type=(int, float), allow_null=True)
            _check_required_field(entry, path, "weight_divergence_pp", issues,
                                  expected_type=(int, float), allow_null=True)
            _check_weight_divergence_consistency(entry, path, issues)
            _check_required_field(entry, path, "on_iis", issues, expected_type=bool)
            # Required analytical fields (LLM-replaced TODO_LLM)
            _check_required_field(entry, path, "fundamental_score", issues,
                                  expected_type=str, allowed_values=VALID_FUNDAMENTAL_SCORE)
            _check_required_field(entry, path, "fundamental_score_basis", issues, expected_type=str)
            # приоритет ставит stamp-report (R28): пустое поле — не ошибка формы, сверка — _priority_check
            _check_required_field(entry, path, "verification_priority", issues,
                                  expected_type=str, allowed_values=VALID_LEVEL_HML, allow_null=True)
            _check_required_field(entry, path, "advisor_verdict", issues,
                                  expected_type=str, allowed_values=VALID_ADVISOR_VERDICT_STOCK)
            _check_required_field(entry, path, "advisor_verdict_confidence", issues,
                                  expected_type=(int, float))
            conf = entry.get("advisor_verdict_confidence")
            if isinstance(conf, (int, float)) and not isinstance(conf, bool) and not (0 <= conf <= 1):
                issues.append({
                    "field": f"{path}.advisor_verdict_confidence",
                    "severity": "blocking",
                    "expected": "0 ≤ confidence ≤ 1",
                    "actual": str(conf),
                })
            _check_required_field(entry, path, "advisor_verdict_basis", issues, expected_type=str)
            # div_yield_12m_pct: {value, ci_pct: [lo, hi]}
            dy = entry.get("div_yield_12m_pct")
            if dy is None:
                issues.append({
                    "field": f"{path}.div_yield_12m_pct",
                    "severity": "blocking",
                    "expected": "object {value, ci_pct: [lo, hi]}",
                    "actual": "missing",
                })
            elif _is_todo_llm(dy):
                issues.append({
                    "field": f"{path}.div_yield_12m_pct",
                    "severity": "blocking",
                    "expected": "object (not TODO_LLM string)",
                    "actual": dy,
                })
            elif not isinstance(dy, dict):
                issues.append({
                    "field": f"{path}.div_yield_12m_pct",
                    "severity": "blocking",
                    "expected": "object {value, ci_pct}",
                    "actual": str(type(dy).__name__),
                })
            else:
                _check_required_field(dy, f"{path}.div_yield_12m_pct", "value", issues,
                                      expected_type=(int, float))
                ci = dy.get("ci_pct")
                if ci is None or _is_todo_llm(ci) or not isinstance(ci, list) or len(ci) != 2:
                    issues.append({
                        "field": f"{path}.div_yield_12m_pct.ci_pct",
                        "severity": "blocking",
                        "expected": "[lo, hi] list of length 2",
                        "actual": str(ci),
                    })
            # catalyst[]
            catalysts = entry.get("catalyst")
            if catalysts is None:
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "list (key 'catalyst', NOT 'catalysts')",
                    "actual": "missing",
                })
            elif _is_todo_llm(catalysts):
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "list of catalyst dicts",
                    "actual": catalysts,
                })
            elif not isinstance(catalysts, list):
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "list",
                    "actual": str(type(catalysts).__name__),
                })
            elif len(catalysts) == 0:
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "≥1 catalyst entry",
                    "actual": "empty list",
                })
            else:
                for idx, cat in enumerate(catalysts):
                    _validate_catalyst(cat, f"{path}.catalyst[{idx}]", issues, v2=v2)
            # dividend_forward (Слой 3 total-return) — optional блок
            _validate_dividend_forward(entry, path, issues, data.get("review_date"))
            _p_outperform_check(entry, path, data.get("review_date"), issues)
            # срез ограничений user_constraints — форма (schema.md §4.2)
            _validate_user_constraints(entry, path, issues, data)
            if v2:
                # Part C: warning при stale verification_priority (opt-in через _priority_context)
                _priority_check(entry, path, (data.get("_priority_context") or {}).get(ticker), issues)
                # R-COV: warning при молчаливом carry-over (источники старше окна без флага)
                _research_freshness_check(entry, path, data.get("review_date"), issues)
            _stale_text_check(entry, path, "stock", issues)
            _week_note_and_confidence_checks(entry, path, issues)
            _catalyst_source_url_check(entry, path, issues)

    if v2:
        _priority_stamp_check(data, "per_stock", issues)
        _obsolete_blocks_check(data, issues)
        _checklist_check(data, "per_stock", issues)
        _sweep_method_check(data, len(per_stock) if isinstance(per_stock, dict) else 0, "акциях", issues)
        _scenario_attribution_check(per_stock if isinstance(per_stock, dict) else {},
                                    "per_stock", issues)
        _trust_attribution_check(per_stock if isinstance(per_stock, dict) else {},
                                 "per_stock", issues)

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


def _validate_bond_plan_fields(entry: dict, path: str, issues: list) -> None:
    """STL-8: опциональные поля плановой таксономии per_bond (bond-subtypes-plan.md §4).

    Back-compat (§4.4): полное отсутствие plan_bucket/plan_subtype/is_floater — валидно,
    не blocking (артефакты до 2026-08-18 их не несут). Если plan_bucket или plan_subtype
    присутствует — валидируем пару по таблице §4.3 (VALID_PLAN_BUCKET_SUBTYPE). Если
    is_floater присутствует — валидируем тип (bool). Все находки — severity warning
    (данные из чужого источника — файла владельца/эвристики, не структурная поломка
    артефакта), симметрично гейтам bond_subtype_missing/bond_subtype_unknown (PDL-7,
    severity warn).

    plan_bucket/plan_subtype ортогональны bond_type и его не заменяют (§4.1); is_floater
    ортогонален bond_type и НЕ подменяет в нём значение floater — ОФЗ-ПК обязана
    оставаться bond_type: ofz и одновременно is_floater: true (решение RPA-14, см.
    yaml-schemas.md). Здесь bond_type не трогаем и не проверяем совместно.
    """
    if "plan_bucket" in entry or "plan_subtype" in entry:
        bucket = entry.get("plan_bucket")
        subtype = entry.get("plan_subtype")
        if bucket not in VALID_PLAN_BUCKET_SUBTYPE:
            issues.append({
                "field": f"{path}.plan_bucket",
                "severity": "warning",
                "expected": f"one of {sorted(VALID_PLAN_BUCKET_SUBTYPE)}",
                "actual": str(bucket),
            })
        elif subtype not in VALID_PLAN_BUCKET_SUBTYPE[bucket]:
            allowed = sorted(s for s in VALID_PLAN_BUCKET_SUBTYPE[bucket] if s is not None)
            expected = f"one of {allowed} for plan_bucket={bucket!r}" if allowed else "null"
            issues.append({
                "field": f"{path}.plan_subtype",
                "severity": "warning",
                "expected": expected,
                "actual": str(subtype),
            })

    if "is_floater" in entry:
        isf = entry.get("is_floater")
        if not isinstance(isf, bool):
            issues.append({
                "field": f"{path}.is_floater",
                "severity": "warning",
                "expected": "bool",
                "actual": f"{type(isf).__name__}: {isf}",
            })


def _validate_bond_rating(entry: dict, path: str, issues: list) -> None:
    """per_bond[ISIN].rating {value, agency, date, source} — необязательный блок (bond-subtypes-plan.md §4.5).

    Нет блока или null — валидно. Форма проверяется как warning (рейтинг берёт загрузчик для вывода корзины;
    кривое значение он молча не использует): value из лестницы §4.2 или «нет рейтинга», agency из списка
    национальных агентств (не нужна при «нет рейтинга»), date — YYYY-MM-DD, source — непустая строка."""
    if "rating" not in entry or entry.get("rating") is None:
        return
    r = entry["rating"]
    if not isinstance(r, dict):
        issues.append({"field": f"{path}.rating", "severity": "warning",
                       "expected": "dict {value, agency, date, source} или null",
                       "actual": f"{type(r).__name__}: {r}"})
        return
    val = r.get("value")
    if val not in VALID_BOND_RATING_VALUES:
        issues.append({"field": f"{path}.rating.value", "severity": "warning",
                       "expected": "значение лестницы AAA…B- или «нет рейтинга»", "actual": str(val)})
    if val != "нет рейтинга" and r.get("agency") not in VALID_RATING_AGENCIES:
        issues.append({"field": f"{path}.rating.agency", "severity": "warning",
                       "expected": f"one of {sorted(VALID_RATING_AGENCIES)}", "actual": str(r.get("agency"))})
    d = r.get("date")
    try:
        ok = isinstance(d, (str, date)) and bool(date.fromisoformat(str(d)[:10]))
    except ValueError:
        ok = False
    if not ok or (isinstance(d, str) and len(d) != 10):
        issues.append({"field": f"{path}.rating.date", "severity": "warning",
                       "expected": "YYYY-MM-DD", "actual": str(d)})
    src = r.get("source")
    if not isinstance(src, str) or not src.strip():
        issues.append({"field": f"{path}.rating.source", "severity": "warning",
                       "expected": "url или текст источника", "actual": str(src)})


def _rating_checked_at_checks(per_bond: dict, data: dict, issues: list) -> None:
    """credit_rating_checked_at: формат (warning, как rating.date) и ОДНО сводное предупреждение
    rating_check_due — корп-бумаги, у которых дата сверки рейтинга пуста или старше порога. Не блокирует."""
    asof = _rating_check.parse_check_date(str(data.get("snapshot_date") or data.get("review_date") or "")[:10])
    for isin, e in per_bond.items():
        if not isinstance(e, dict) or e.get("credit_rating_checked_at") is None:
            continue
        v = e["credit_rating_checked_at"]
        d = _rating_check.parse_check_date(v) if isinstance(v, str) else None
        if d is None:
            issues.append({"field": f"per_bond.{isin}.credit_rating_checked_at", "severity": "warning",
                           "expected": "YYYY-MM-DD или null", "actual": str(v)})
        elif asof is not None and d > asof:
            issues.append({"field": f"per_bond.{isin}.credit_rating_checked_at", "severity": "warning",
                           "expected": f"не позже даты данных обзора ({asof.isoformat()})", "actual": str(v)})
    if asof is None:
        return
    due = _rating_check.bonds_due_for_rating_check(per_bond, asof)
    if due:
        issues.append({"field": "rating_check_due", "severity": "warning",
                       "expected": f"credit_rating_checked_at не старше {_rating_check.RATING_CHECK_MAX_AGE_DAYS} дн. "
                                   "у корпоративных бумаг",
                       "actual": f"Рейтинг пора перепроверить (дата проверки пуста или старше "
                                 f"{_rating_check.RATING_CHECK_MAX_AGE_DAYS} дн.): "
                                 + ", ".join(_rating_check.due_label(d) for d in due)})


def validate_weekly_review_bond_detailed(data: dict) -> dict:
    """Детальная валидация weekly-review-bond YAML.

    Канон: схема `weekly-bonds-review` из `_shared-references/yaml-schemas.md` §7b / §11.
    Только schema_version 2 (v1-приём снят V2-CUTOVER 2026-08-03; мигратор:
    skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py).
    Блокирует если:
    - Top-level: schema_version != 2, type != "weekly-bonds-review",
      review_date/snapshot_id отсутствуют, per_bond пуст; горизонт-блок невалиден
      или присутствует v1-поле горизонта
    - summary блок: отсутствуют total_value_rub / weighted_ytm_pct /
      weighted_duration_days / by_type_pct / by_credit_quality_pct / maturity_ladder_pct
    - Anti-rename: summary.bonds_total_rub без summary.total_value_rub
    - На каждом bond entry: TODO_LLM, missing required, неверный bond_type/credit_quality enum
    """
    issues: list[dict] = []
    v2 = (data.get("schema_version") == 2 and not isinstance(data.get("schema_version"), bool))

    # === Top-level ===
    if not v2:
        sv = data.get("schema_version")
        issues.append({
            "field": "schema_version",
            "severity": "blocking",
            "expected": "2 (integer; v1 снят V2-CUTOVER 2026-08-03 — "
                        "миграция: migrate_v1_to_v2.py)",
            "actual": f"{type(sv).__name__}: {sv!r}",
        })
    if data.get("type") != "weekly-bonds-review":
        issues.append({"field": "type", "severity": "blocking",
                       "expected": "'weekly-bonds-review'", "actual": str(data.get("type"))})
    for f in ("review_date", "snapshot_id"):
        if not data.get(f):
            issues.append({"field": f, "severity": "blocking",
                           "expected": "non-empty string", "actual": str(data.get(f))})
    _validate_horizons_block(data, issues)
    _check_v1_horizon_fields_in_v2(data, issues)

    # === summary block ===
    summary = data.get("summary")
    if not isinstance(summary, dict):
        issues.append({
            "field": "summary",
            "severity": "blocking",
            "expected": "dict with weighted_ytm_pct, total_value_rub, by_type_pct, …",
            "actual": str(type(summary).__name__) if summary else "missing",
        })
    else:
        # Anti-drift: bonds_total_rub только если есть total_value_rub
        if "bonds_total_rub" in summary and "total_value_rub" not in summary:
            issues.append({
                "field": "summary.bonds_total_rub",
                "severity": "blocking",
                "expected": "canonical name 'total_value_rub' (можно также продублировать как bonds_total_rub)",
                "actual": "only 'bonds_total_rub' present",
            })
        for sf in ("total_value_rub",):
            v = summary.get(sf)
            if v is None or _is_todo_llm(v):
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "non-null number",
                    "actual": str(v),
                })
        # weighted_ytm_pct: либо число, либо {value, ci_pct}
        wy = summary.get("weighted_ytm_pct")
        if wy is None:
            issues.append({
                "field": "summary.weighted_ytm_pct",
                "severity": "blocking",
                "expected": "number or {value, ci_pct}",
                "actual": "missing",
            })
        elif _is_todo_llm(wy):
            issues.append({
                "field": "summary.weighted_ytm_pct",
                "severity": "blocking",
                "expected": "filled (not TODO_LLM)",
                "actual": wy,
            })
        elif isinstance(wy, dict):
            _check_required_field(wy, "summary.weighted_ytm_pct", "value", issues,
                                  expected_type=(int, float))
            ci = wy.get("ci_pct")
            if ci is None or not isinstance(ci, list) or len(ci) != 2 or _is_todo_llm(ci):
                issues.append({
                    "field": "summary.weighted_ytm_pct.ci_pct",
                    "severity": "blocking",
                    "expected": "[lo, hi] list",
                    "actual": str(ci),
                })
        elif not isinstance(wy, (int, float)) or isinstance(wy, bool):
            issues.append({
                "field": "summary.weighted_ytm_pct",
                "severity": "blocking",
                "expected": "number or {value, ci_pct}",
                "actual": str(type(wy).__name__),
            })
        # weighted_duration_days: число (не объект)
        wd = summary.get("weighted_duration_days")
        if wd is None or _is_todo_llm(wd):
            issues.append({
                "field": "summary.weighted_duration_days",
                "severity": "blocking",
                "expected": "integer number",
                "actual": str(wd),
            })
        elif not isinstance(wd, (int, float)) or isinstance(wd, bool):
            issues.append({
                "field": "summary.weighted_duration_days",
                "severity": "blocking",
                "expected": "integer/float",
                "actual": f"{type(wd).__name__}: {wd}",
            })
        # by_type_pct, by_credit_quality_pct, maturity_ladder_pct — dicts
        for sf in ("by_type_pct", "by_credit_quality_pct", "maturity_ladder_pct"):
            v = summary.get(sf)
            if v is None:
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "dict",
                    "actual": "missing",
                })
            elif _is_todo_llm(v):
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "filled dict (not TODO_LLM)",
                    "actual": v,
                })
            elif not isinstance(v, dict):
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "dict",
                    "actual": str(type(v).__name__),
                })
            elif len(v) == 0:
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "non-empty dict",
                    "actual": "empty dict",
                })
        # by_credit_quality_pct keys must be subset of HIGH/MEDIUM/LOW
        bcq = summary.get("by_credit_quality_pct")
        if isinstance(bcq, dict):
            invalid_keys = set(bcq.keys()) - VALID_LEVEL_HML
            if invalid_keys:
                issues.append({
                    "field": "summary.by_credit_quality_pct",
                    "severity": "blocking",
                    "expected": "keys ⊆ {HIGH, MEDIUM, LOW}",
                    "actual": f"unknown keys: {sorted(invalid_keys)}",
                })

    # === per_bond ===
    per_bond = data.get("per_bond")
    if not per_bond or not isinstance(per_bond, dict):
        issues.append({
            "field": "per_bond",
            "severity": "blocking",
            "expected": "non-empty dict of {ISIN: position}",
            "actual": str(type(per_bond).__name__) if per_bond else "missing/empty",
        })
    else:
        for isin, entry in per_bond.items():
            path = f"per_bond.{isin}"
            if not isinstance(entry, dict):
                issues.append({
                    "field": path,
                    "severity": "blocking",
                    "expected": "dict",
                    "actual": str(type(entry).__name__),
                })
                continue
            # Anti-drift renames (если будут добавлены позже)
            for drift, canonical in (("share_actual_pct", "weight_real_pct"),):
                if drift in entry:
                    issues.append({
                        "field": f"{path}.{drift}",
                        "severity": "blocking",
                        "expected": f"canonical name '{canonical}'",
                        "actual": f"drift-rename '{drift}'",
                    })
            # Required deterministic fields
            _check_required_field(entry, path, "name", issues, expected_type=str)
            _check_required_field(entry, path, "weight_real_pct", issues,
                                  expected_type=(int, float))
            _check_required_field(entry, path, "on_iis", issues, expected_type=bool)
            _check_required_field(entry, path, "bond_type", issues,
                                  expected_type=str, allowed_values=VALID_BOND_TYPE)
            _check_required_field(entry, path, "maturity_date", issues, expected_type=str)
            _check_required_field(entry, path, "ytm_pct", issues, expected_type=(int, float))
            # Analytical fields (LLM-filled)
            _check_required_field(entry, path, "credit_quality", issues,
                                  expected_type=str, allowed_values=VALID_LEVEL_HML)
            _check_required_field(entry, path, "advisor_verdict", issues,
                                  expected_type=str, allowed_values=VALID_ADVISOR_VERDICT_BOND)
            _p_outperform_check(entry, path, data.get("review_date"), issues)
            _check_required_field(entry, path, "advisor_verdict_basis", issues, expected_type=str)
            _check_required_field(entry, path, "verification_priority", issues,
                                  expected_type=str, allowed_values=VALID_LEVEL_HML, allow_null=True)
            if v2:
                _priority_check(entry, path, (data.get("_priority_context") or {}).get(isin), issues)
            _stale_text_check(entry, path, "bond", issues)
            _week_note_and_confidence_checks(entry, path, issues)
            _catalyst_source_url_check(entry, path, issues)
            # catalyst[]
            catalysts = entry.get("catalyst")
            if catalysts is None:
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "list (key 'catalyst', NOT 'catalysts')",
                    "actual": "missing",
                })
            elif _is_todo_llm(catalysts):
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "list",
                    "actual": catalysts,
                })
            elif not isinstance(catalysts, list) or len(catalysts) == 0:
                issues.append({
                    "field": f"{path}.catalyst",
                    "severity": "blocking",
                    "expected": "≥1 catalyst entry",
                    "actual": str(catalysts)[:40],
                })
            else:
                for idx, cat in enumerate(catalysts):
                    _validate_catalyst(cat, f"{path}.catalyst[{idx}]", issues, v2=v2)
            # срез ограничений user_constraints — форма (schema.md §4.2), так же для облигаций
            _validate_user_constraints(entry, path, issues, data)
            # plan_bucket/plan_subtype/is_floater (STL-7/8, bond-subtypes-plan.md §4) — optional блок
            _validate_bond_plan_fields(entry, path, issues)
            # rating {value, agency, date, source} (§4.5) — optional блок
            _validate_bond_rating(entry, path, issues)

    if isinstance(per_bond, dict):
        _rating_checked_at_checks(per_bond, data, issues)

    if v2:
        _priority_stamp_check(data, "per_bond", issues)
        _obsolete_blocks_check(data, issues)
        _checklist_check(data, "per_bond", issues)
        corp_issuers = {(e.get("issuer") or k) for k, e in (per_bond or {}).items()
                        if isinstance(e, dict) and e.get("bond_type") != "ofz"} if isinstance(per_bond, dict) else set()
        _sweep_method_check(data, len(corp_issuers), "корпоративных эмитентах", issues)
        _scenario_attribution_check(per_bond if isinstance(per_bond, dict) else {},
                                    "per_bond", issues)
        _trust_attribution_check(per_bond if isinstance(per_bond, dict) else {},
                                 "per_bond", issues)

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


def validate_weekly_review(data: dict) -> dict:
    """Router by `type`. Detailed validators for canonical types; basic legacy fallback."""
    artifact_type = data.get("type", "")
    if artifact_type == "weekly-stocks-review":
        return validate_weekly_review_stock_detailed(data)
    if artifact_type == "weekly-bonds-review":
        return validate_weekly_review_bond_detailed(data)

    # Legacy / unknown — basic check (review_date + snapshot_id + per_*)
    issues: list[dict] = []
    for field in ("review_date", "snapshot_id"):
        if not data.get(field):
            issues.append({
                "field": field,
                "severity": "blocking",
                "expected": "non-empty value",
                "actual": None,
            })
    if artifact_type == "weekly-bonds-review":
        per_bond = data.get("per_bond")
        if not per_bond or (isinstance(per_bond, (dict, list)) and len(per_bond) == 0):
            issues.append({
                "field": "per_bond",
                "severity": "blocking",
                "expected": "at least one bond position present",
                "actual": None,
            })
        summary = data.get("summary") or {}
        for sf in ("weighted_ytm_pct", "by_type_pct", "maturity_ladder_pct"):
            if sf not in summary:
                issues.append({
                    "field": f"summary.{sf}",
                    "severity": "blocking",
                    "expected": "present in summary block",
                    "actual": None,
                })
    else:
        per_stock = data.get("per_stock")
        if not per_stock or (isinstance(per_stock, (dict, list)) and len(per_stock) == 0):
            issues.append({
                "field": "per_stock",
                "severity": "blocking",
                "expected": "at least one stock position present",
                "actual": None,
            })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# validate-snapshot (H)
# ---------------------------------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iv_check_metric(obj, path: str, issues: list, *, required: bool) -> None:
    """{value: <num>, ci: [num,num]|null} — числа ЧИСЛАМИ (не '+13.6%'-строками)."""
    if obj is None:
        if required:
            issues.append({"field": path, "severity": "blocking",
                           "expected": "{value, ci}", "actual": None})
        return
    if not isinstance(obj, dict) or not _is_num(obj.get("value")):
        issues.append({
            "field": f"{path}.value", "severity": "blocking",
            "expected": "число (не строка вида '+13.6%' — контракт @1.3: блок "
                        "копируется as-is из aggregate_positions.py)",
            "actual": repr(obj if not isinstance(obj, dict) else obj.get("value")),
        })
        return
    ci = obj.get("ci")
    if ci is not None and (not isinstance(ci, list) or len(ci) != 2
                           or not all(_is_num(x) for x in ci)):
        issues.append({"field": f"{path}.ci", "severity": "blocking",
                       "expected": "[lo, hi] числа или null", "actual": repr(ci)})


def validate_integrated_view(data: dict) -> dict:
    """Валидация frontmatter integrated-view (Workflow G, контракт @1.3).

    Цель — чтобы машинно-потребляемые блоки (portfolio_by_horizon, total_return)
    НЕ выводились «LLM-форматированием»: числа числами, даты строками в кавычках
    (иначе js-yaml вьюера отдаёт Date), ключи-горизонты сходятся с horizons.
    @≤1.2 — только warning «старый формат» (legacy-сейвы не блокируем).
    Payload = распарсенный YAML frontmatter артефакта.
    """
    issues: list[dict] = []
    sv = str(data.get("schema_version") or "")
    m = re.match(r"^integrated-view@(\d+)\.(\d+)$", sv)
    if not m:
        issues.append({"field": "schema_version", "severity": "blocking",
                       "expected": "integrated-view@X.Y (напр. integrated-view@1.3)",
                       "actual": sv or None})
        return {"valid": False, "blocking_count": 1, "issues": issues}
    minor = (int(m.group(1)), int(m.group(2)))
    if minor < (1, 3):
        issues.append({
            "field": "schema_version", "severity": "warning",
            "expected": "integrated-view@1.3 (структурные блоки для графиков)",
            "actual": f"{sv} — старый формат: вьюер рисует §4 из прозы «через раз»",
        })
        blocking = _blocking(issues)
        return {"valid": True, "blocking_count": 0,
                "warning_count": len(issues), "issues": issues}

    # ── @1.3: горизонт-блок §11.0 + отсутствие v1-полей ──
    _validate_horizons_block(data, issues)
    _check_v1_horizon_fields_in_v2(data, issues)
    if data.get("ci_method") not in ("mc", "analytic"):
        issues.append({"field": "ci_method", "severity": "blocking",
                       "expected": "'mc' | 'analytic'", "actual": str(data.get("ci_method"))})

    horizons = data.get("horizons") if isinstance(data.get("horizons"), list) else []
    expected_keys = {str(int(h)) for h in horizons if isinstance(h, int)}

    # ── portfolio_by_horizon (контракт стабильности графиков) ──
    pbh = data.get("portfolio_by_horizon")
    if not isinstance(pbh, dict):
        issues.append({"field": "portfolio_by_horizon", "severity": "blocking",
                       "expected": "dict (copy as-is из result"
                                   "['frontmatter_portfolio_by_horizon'])",
                       "actual": type(pbh).__name__ if pbh is not None else None})
    else:
        ph = pbh.get("primary_horizon")
        if not isinstance(ph, int) or (horizons and ph not in horizons):
            issues.append({"field": "portfolio_by_horizon.primary_horizon",
                           "severity": "blocking",
                           "expected": f"int ∈ {horizons}", "actual": repr(ph)})
        hs = pbh.get("horizons")
        if not isinstance(hs, dict) or not hs:
            issues.append({"field": "portfolio_by_horizon.horizons",
                           "severity": "blocking",
                           "expected": 'dict {"12": {...}}', "actual": repr(hs)})
        else:
            keys = {str(k) for k in hs.keys()}
            if expected_keys and keys != expected_keys:
                issues.append({
                    "field": "portfolio_by_horizon.horizons", "severity": "blocking",
                    "expected": f"ключи-месяцы = {sorted(expected_keys)}",
                    "actual": f"{sorted(keys)} (несовпадение с top-level horizons)",
                })
            for k, e in hs.items():
                p = f"portfolio_by_horizon.horizons.{k}"
                if not isinstance(e, dict):
                    issues.append({"field": p, "severity": "blocking",
                                   "expected": "dict", "actual": type(e).__name__})
                    continue
                end = e.get("end")
                if end is not None and not isinstance(end, str):
                    issues.append({
                        "field": f"{p}.end", "severity": "blocking",
                        "expected": "строка 'YYYY-MM-DD' В КАВЫЧКАХ (нестрочная дата "
                                    "→ js-yaml вьюера отдаёт Date-объект)",
                        "actual": type(end).__name__,
                    })
                _iv_check_metric(e.get("equity"), f"{p}.equity", issues, required=True)
                _iv_check_metric(e.get("bond"), f"{p}.bond", issues, required=True)
                _iv_check_metric(e.get("spread"), f"{p}.spread", issues, required=False)

    # ── total_return (полоса «три слоя») — опционален, но если есть — строго ──
    tr = data.get("total_return")
    if tr is not None:
        trh = tr.get("horizons") if isinstance(tr, dict) else None
        if not isinstance(trh, dict) or not trh:
            issues.append({"field": "total_return.horizons", "severity": "blocking",
                           "expected": 'dict {"12": {expected, layers}}',
                           "actual": repr(trh)})
        else:
            for k, e in trh.items():
                p = f"total_return.horizons.{k}"
                exp = (e or {}).get("expected")
                if not isinstance(exp, dict):
                    issues.append({"field": f"{p}.expected", "severity": "blocking",
                                   "expected": "dict {portfolio, equity, bond, cash}",
                                   "actual": repr(exp)})
                    continue
                for b, v in exp.items():
                    if v is not None and not _is_num(v):
                        issues.append({"field": f"{p}.expected.{b}",
                                       "severity": "blocking",
                                       "expected": "число или null", "actual": repr(v)})
                for b, layer in ((e or {}).get("layers") or {}).items():
                    for lk, lv in (layer or {}).items():
                        if lk == "flags":
                            continue
                        if lv is not None and not _is_num(lv):
                            issues.append({"field": f"{p}.layers.{b}.{lk}",
                                           "severity": "blocking",
                                           "expected": "число или null",
                                           "actual": repr(lv)})

    # ── мягкие проверки (warning) ──
    if not isinstance(data.get("tail_flags"), dict):
        issues.append({"field": "tail_flags", "severity": "warning",
                       "expected": "dict (copy as-is, @1.2+)", "actual": None})
    inputs = data.get("inputs") or {}
    ages = [k for k in ("snapshot_age_days", "stress_age_days", "review_age_days")
            if not _is_num(inputs.get(k))]
    if ages:
        issues.append({"field": "inputs", "severity": "warning",
                       "expected": "*_age_days явными числами (U4, иначе вьюер "
                                   "показывает «возраст: —д»)",
                       "actual": f"нет/не числа: {ages}"})

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "warning_count": len(issues) - len(blocking),
        "issues": issues,
    }


def validate_portfolio_snapshot(data: dict) -> dict:
    """Validate portfolio snapshot JSON required fields (Workflow H logic)."""
    issues: list[dict] = []

    schema_version = data.get("schema_version")
    if schema_version != "2.0":
        issues.append({
            "field": "schema_version",
            "severity": "blocking",
            "expected": '"2.0"',
            "actual": str(schema_version) if schema_version is not None else None,
        })

    positions = data.get("positions")
    if not positions or not isinstance(positions, list) or len(positions) == 0:
        issues.append({
            "field": "positions",
            "severity": "blocking",
            "expected": "non-empty list",
            "actual": None,
        })

    total_value = data.get("total_value")
    if total_value is None:
        issues.append({
            "field": "total_value",
            "severity": "blocking",
            "expected": "numeric > 0",
            "actual": None,
        })
    else:
        try:
            if float(total_value) <= 0:
                issues.append({
                    "field": "total_value",
                    "severity": "blocking",
                    "expected": "value > 0",
                    "actual": str(total_value),
                })
        except (TypeError, ValueError):
            issues.append({
                "field": "total_value",
                "severity": "blocking",
                "expected": "numeric float > 0",
                "actual": str(total_value),
            })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# --- F4 polarity-lock (events-yaml-spec.md §17) ---
POLARITY_STRESS_POLE_CANON = "A"     # канон: Sc-A = максимальный стресс
POLARITY_DETENTE_POLE_CANON = "D"    # канон: Sc-D = максимальная разрядка
VALID_SCENARIO_POLE = {"A", "B", "C", "D"}


def _validate_polarity(data: dict, issues: list) -> None:
    """F4 polarity-lock (events-yaml-spec.md §17, warning-only): канон Sc-A = макс. стресс,
    Sc-D = макс. разрядка. Смена полярности только с axis_polarity_change:true + миграция A↔D.
    Бьёт по process-churn от инверсий осей (self-audit №4а)."""
    matrix = data.get("matrix")
    if not isinstance(matrix, dict):
        return
    polarity = matrix.get("polarity")
    change = bool(matrix.get("axis_polarity_change"))
    migration = matrix.get("axis_polarity_migration")

    if polarity is None:
        issues.append(_issue("matrix.polarity", "warning",
                             "задекларируй {stress_pole: A, detente_pole: D} (канон §17)", None))
    elif not isinstance(polarity, dict):
        issues.append(_issue("matrix.polarity", "warning",
                             "dict {stress_pole, detente_pole}", type(polarity).__name__))
    else:
        sp = polarity.get("stress_pole")
        dp = polarity.get("detente_pole")
        if sp not in VALID_SCENARIO_POLE or dp not in VALID_SCENARIO_POLE:
            issues.append(_issue("matrix.polarity", "warning",
                                 f"stress_pole/detente_pole ∈ {sorted(VALID_SCENARIO_POLE)}",
                                 f"{sp}/{dp}"))
        elif sp == dp:
            issues.append(_issue("matrix.polarity", "warning", "stress_pole != detente_pole",
                                 f"{sp}/{dp}"))
        elif (sp != POLARITY_STRESS_POLE_CANON or dp != POLARITY_DETENTE_POLE_CANON) and not change:
            issues.append(_issue("matrix.polarity", "warning",
                                 f"рассинхрон с каноном (стресс={POLARITY_STRESS_POLE_CANON}, "
                                 f"разрядка={POLARITY_DETENTE_POLE_CANON}); смена только с "
                                 "axis_polarity_change:true + таблица миграции A↔D",
                                 f"{sp}/{dp}"))

    if change and not (isinstance(migration, dict) and migration):
        issues.append(_issue("matrix.axis_polarity_migration", "warning",
                             "axis_polarity_change:true требует непустую таблицу миграции A↔D", None))


def validate_scenario_events(data: dict) -> dict:
    issues: list[dict] = []

    _validate_polarity(data, issues)

    for field in ("type", "schema_version", "matrix", "scenario_triggers", "reviews"):
        if data.get(field) is None:
            issues.append({
                "field": field,
                "severity": "blocking",
                "expected": "present",
                "actual": None,
            })

    triggers = data.get("scenario_triggers")
    if not isinstance(triggers, list) or len(triggers) == 0:
        issues.append({
            "field": "scenario_triggers",
            "severity": "blocking",
            "expected": "non-empty list",
            "actual": type(triggers).__name__,
        })
    else:
        # Σ probability ∈ [0.98, 1.02] — warning, not blocking (rounding tolerance ±2%)
        try:
            prob_sum = sum(
                float(t["probability"]) if isinstance(t, dict) and "probability" in t else 0
                for t in triggers
            )
            if not (0.98 <= prob_sum <= 1.02):
                issues.append({
                    "field": "scenario_triggers[*].probability",
                    "severity": "warning",
                    "expected": "sum ≈ 1.0 (±0.02)",
                    "actual": f"{prob_sum:.4f}",
                })
        except (TypeError, ValueError):
            issues.append({
                "field": "scenario_triggers[*].probability",
                "severity": "blocking",
                "expected": "numeric values",
                "actual": "parse error",
            })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# validate-forecast-events (events-yaml-spec.md §5)
# ---------------------------------------------------------------------------

# inferred_from_content — D8-канон (FCA Шаг 1.5B); был потерян при ужесточении, восстановлен
# по SSOT events-yaml-spec.md §5.2/§6.1 (валидатор отставал от спеки).
VALID_PROVENANCE = {
    "native_fca", "single_native", "derived_from_marginal", "inferred_from_content",
    # FCA-3 канон (events-yaml-spec.md §5.2.1, 2026-08-03):
    "derived_from_upstream", "derived_from_geopolitics_translation",
}

# Стихийные легаси-имена provenance из живых файлов 2026-05-11 → канон (§5.2.1).
# Используется для внятного сообщения валидатора и миграционного скрипта.
LEGACY_PROVENANCE_MAP = {
    "source_native": "single_native",
    "inferred_from_cpi_floor": "derived_from_upstream",
    "inferred_from_upstream_dependency": "derived_from_upstream",
    "structural_derivation": "derived_from_upstream",
}

# provenance, требующие непустой sources_used (список объектов) — §5.2.1.
_PROVENANCE_NEEDS_SOURCES = {"native_fca", "single_native", "inferred_from_content"}
VALID_COVERAGE_QUALITY = {"HIGH", "MEDIUM", "LOW", "DERIVED"}
VALID_MARGINAL_METHOD = {"linear", "nonlinear", "axis_dependent", "indifferent", "modal"}
VALID_MODAL_SCENARIO = {"A", "B", "C", "D", "none"}
VALID_COHERENCE_SEVERITY = {"LOW", "MEDIUM", "HIGH", "N/A"}   # N/A — F5: L2 не несёт информации
REQUIRED_BY_SCENARIO_KEYS = {"A", "B", "C", "D"}

# --- Калибровочные блоки outcome_log / fca_stats (events-yaml-spec.md §14) ---
VALID_OUTCOME_KIND = {"level", "event"}
VALID_RECORD_TYPE = {"horizon_resolve", "interim_supersession"}
VALID_SHOCK_FLAG = {"none", "exogenous_shock"}

# --- Односторонний сценарный конус (events-yaml-spec.md §15, F1) ---
VALID_CONE_SIDE = {"up", "down", "two_sided", "neutral"}
VALID_FALSIFIER_SIDE = {"up", "down", "both"}
CONE_EPS_REL = 0.005          # 0.5% от |anchor|
# Якорные сроки держатся от прогона к прогону и сдвигаются на полгода, когда до ближайшего остаётся
# меньше трёх месяцев (stress_build.shift_horizons), поэтому метка hNN расходится с фактом до трёх месяцев.
ANCHORED_TOL_MONTHS = 3
CONE_EPS_ABS_FLOOR = 1e-9     # чтобы eps>0 при anchor=0 (формат дельт macro-scenarios)


def _is_num(x) -> bool:
    """True для int/float, но НЕ для bool (bool — подкласс int)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _validate_fca_stats(data: dict, issues: list) -> None:
    """Аддитивная валидация опционального `fca_stats` (events-yaml-spec.md §14.1).

    Живой машинный слепок точечной оценки FCA (per-horizon). Только type-проверки —
    это диагностический бэкбон, не строгий контракт. Отсутствие блока — не ошибка.
    """
    fca_stats = data.get("fca_stats")
    if fca_stats is None:
        return
    if not isinstance(fca_stats, dict):
        issues.append(_issue("fca_stats", "blocking", "dict keyed by horizon-date", type(fca_stats).__name__))
        return
    for hz, entry in fca_stats.items():
        prefix = f"fca_stats.{hz}"
        if not _DATE_RE.match(str(hz)):
            issues.append(_issue(prefix, "warning", "ключ — дата YYYY-MM-DD (горизонт/событие)", hz))
        if not isinstance(entry, dict):
            issues.append(_issue(prefix, "blocking", "dict", type(entry).__name__))
            continue
        kind = entry.get("kind")
        if kind not in VALID_OUTCOME_KIND:
            issues.append(_issue(f"{prefix}.kind", "blocking", f"one of {sorted(VALID_OUTCOME_KIND)}", str(kind)))
        for f in ("l1_weighted", "l1_unweighted", "l2_ev", "p10", "p90", "predicted_p"):
            v = entry.get(f)
            if v is not None and not _is_num(v):
                issues.append(_issue(f"{prefix}.{f}", "blocking", "number or null", str(v)))
        pp = entry.get("predicted_p")
        if _is_num(pp) and not (0 <= pp <= 1):
            issues.append(_issue(f"{prefix}.predicted_p", "blocking", "0..1", str(pp)))
        p10, p90 = entry.get("p10"), entry.get("p90")
        if _is_num(p10) and _is_num(p90) and p10 > p90:
            issues.append(_issue(f"{prefix}.p10/p90", "blocking", "p10 <= p90", f"{p10} > {p90}"))


def _validate_outcome_log_entry(e: dict, prefix: str, issues: list) -> None:
    """Валидация одной записи outcome_log (events-yaml-spec.md §14.2)."""
    for f in ("resolve_date", "logged_at"):
        v = e.get(f)
        if not v:
            issues.append(_issue(f"{prefix}.{f}", "blocking", "YYYY-MM-DD", None))
        elif not _DATE_RE.match(str(v)):
            issues.append(_issue(f"{prefix}.{f}", "blocking", "YYYY-MM-DD", str(v)))

    rt = e.get("record_type")
    if rt not in VALID_RECORD_TYPE:
        issues.append(_issue(f"{prefix}.record_type", "blocking", f"one of {sorted(VALID_RECORD_TYPE)}", str(rt)))

    kind = e.get("kind")
    if kind not in VALID_OUTCOME_KIND:
        issues.append(_issue(f"{prefix}.kind", "blocking", f"one of {sorted(VALID_OUTCOME_KIND)}", str(kind)))

    sf = e.get("shock_flag", "none")
    if sf not in VALID_SHOCK_FLAG:
        issues.append(_issue(f"{prefix}.shock_flag", "blocking", f"one of {sorted(VALID_SHOCK_FLAG)}", str(sf)))

    caf = e.get("confidence_at_forecast")
    if caf is None:
        issues.append(_issue(f"{prefix}.confidence_at_forecast", "warning",
                             "0..1 (для reliability по confidence)", None))
    elif not _is_num(caf) or not (0 <= caf <= 1):
        issues.append(_issue(f"{prefix}.confidence_at_forecast", "blocking", "0..1", str(caf)))

    actual = e.get("actual")
    resolved = e.get("resolved")

    if kind == "level":
        _validate_outcome_level(e, prefix, issues, actual, resolved)
    elif kind == "event":
        _validate_outcome_event(e, prefix, issues, actual, resolved)


def _validate_outcome_level(e: dict, prefix: str, issues: list, actual, resolved) -> None:
    flw = e.get("forecast_l1_weighted")
    if flw is None:
        # Заморожённое L1 weighted обязательно при наличии факта (иначе error_pct не посчитать).
        sev = "blocking" if actual is not None else "warning"
        issues.append(_issue(f"{prefix}.forecast_l1_weighted", sev,
                             "number (frozen L1 weighted, на момент прогноза)", None))
    elif not _is_num(flw):
        issues.append(_issue(f"{prefix}.forecast_l1_weighted", "blocking", "number", str(flw)))

    flu = e.get("forecast_l1_unweighted")
    if flu is None:
        issues.append(_issue(f"{prefix}.forecast_l1_unweighted", "warning",
                             "number — тест weighted-vs-unweighted; иначе null # TODO", None))
    elif not _is_num(flu):
        issues.append(_issue(f"{prefix}.forecast_l1_unweighted", "blocking", "number or null", str(flu)))

    fl2 = e.get("forecast_l2_ev")
    if fl2 is not None and not _is_num(fl2):
        issues.append(_issue(f"{prefix}.forecast_l2_ev", "blocking", "number or null (Type 1 → null)", str(fl2)))

    pp = e.get("p10_p90")
    if pp is None:
        issues.append(_issue(f"{prefix}.p10_p90", "warning",
                             "[lo, hi] — interval-coverage; иначе null # TODO", None))
    elif not (isinstance(pp, list) and len(pp) == 2 and _is_num(pp[0]) and _is_num(pp[1])):
        issues.append(_issue(f"{prefix}.p10_p90", "blocking", "[lo, hi] numeric", str(pp)))
    elif pp[0] > pp[1]:
        issues.append(_issue(f"{prefix}.p10_p90", "blocking", "lo <= hi", str(pp)))

    if e.get("predicted_p") is not None:
        issues.append(_issue(f"{prefix}.predicted_p", "warning",
                             "event-only; для kind:level не заполняется", str(e.get("predicted_p"))))
    if resolved is not None:
        issues.append(_issue(f"{prefix}.resolved", "warning",
                             "event-only; для kind:level исход в actual", str(resolved)))

    if actual is not None and not _is_num(actual):
        issues.append(_issue(f"{prefix}.actual", "blocking", "number or null", str(actual)))

    # На резолве (actual задан) — derived-поля и провенанс должны быть заполнены.
    if actual is not None:
        if e.get("error_pct") is None and _is_num(flw) and flw != 0:
            issues.append(_issue(f"{prefix}.error_pct", "warning",
                                 "заполнить helper'ом `complete-outcome-log`", None))
        if e.get("in_p10_p90") is None and isinstance(pp, list) and len(pp) == 2:
            issues.append(_issue(f"{prefix}.in_p10_p90", "warning",
                                 "заполнить helper'ом `complete-outcome-log`", None))
        if not e.get("actual_source"):
            issues.append(_issue(f"{prefix}.actual_source", "warning", "провенанс факта (URL/файл)", None))


def _validate_outcome_event(e: dict, prefix: str, issues: list, actual, resolved) -> None:
    pp = e.get("predicted_p")
    if resolved is not None:
        if resolved not in (0, 1, True, False):
            issues.append(_issue(f"{prefix}.resolved", "blocking", "0 | 1 | null", str(resolved)))
        if pp is None:
            issues.append(_issue(f"{prefix}.predicted_p", "blocking",
                                 "0..1 — нельзя Brier-скорить резолв события без p", None))
        elif not _is_num(pp) or not (0 <= pp <= 1):
            issues.append(_issue(f"{prefix}.predicted_p", "blocking", "0..1", str(pp)))
        if not e.get("actual_source"):
            issues.append(_issue(f"{prefix}.actual_source", "warning", "провенанс исхода (URL/файл)", None))
    else:
        # Нерезолвнутый stub: predicted_p ещё может быть null (grandfather), но это надо заполнить.
        if pp is None:
            issues.append(_issue(f"{prefix}.predicted_p", "warning",
                                 "event-stub без predicted_p — заполнить до резолва, иначе Brier невозможен", None))
        elif not _is_num(pp) or not (0 <= pp <= 1):
            issues.append(_issue(f"{prefix}.predicted_p", "blocking", "0..1 or null", str(pp)))

    for f in ("forecast_l1_weighted", "forecast_l1_unweighted", "forecast_l2_ev",
              "p10_p90", "error_pct", "in_p10_p90"):
        if e.get(f) is not None:
            issues.append(_issue(f"{prefix}.{f}", "warning",
                                 "level-only; для kind:event не заполняется", str(e.get(f))))
    if actual is not None:
        issues.append(_issue(f"{prefix}.actual", "warning",
                             "для kind:event исход в resolved (0|1), не в actual", str(actual)))


def _validate_outcome_log(data: dict, issues: list) -> None:
    """Аддитивная валидация опционального `outcome_log` (events-yaml-spec.md §14.2)."""
    log = data.get("outcome_log")
    if log is None:
        return
    if not isinstance(log, list):
        issues.append(_issue("outcome_log", "blocking", "list of entries", type(log).__name__))
        return
    for idx, e in enumerate(log):
        prefix = f"outcome_log[{idx}]"
        if not isinstance(e, dict):
            issues.append(_issue(prefix, "blocking", "dict", type(e).__name__))
            continue
        _validate_outcome_log_entry(e, prefix, issues)


def complete_outcome_log(data: dict) -> dict:
    """Helper: дозаполнить запись outcome_log на резолве (детерминированная арифметика).

    Вход: {"entry": {...}} — запись с проставленным `actual` (level) и/или `resolved` (event).
    Считает `error_pct` = (actual − forecast_l1_weighted)/forecast_l1_weighted × 100 и
    `in_p10_p90` = p10 <= actual <= p90. Никакой LLM-арифметики (events-yaml-spec.md §14.4).
    Факт без замороженного прогноза (level без числа `forecast_l1_weighted`, event без `predicted_p`) — blocking,
    и факт в возвращаемой записи обнулён: помощник не отдаёт запись, которую валидатор потом заблокирует.
    """
    entry = dict(data.get("entry") or {})
    issues: list[dict] = []
    kind = entry.get("kind")

    if kind == "level":
        actual = entry.get("actual")
        flw = entry.get("forecast_l1_weighted")
        if actual is not None and not _is_num(flw):
            issues.append(_issue("entry.forecast_l1_weighted", "blocking",
                                 "нет замороженного прогноза слоя 1 — факт записывать нельзя; actual оставлен null",
                                 None if flw is None else str(flw)))
            entry.update(actual=None, error_pct=None, in_p10_p90=None)
            actual = None
        elif actual is None or not _is_num(actual):
            issues.append(_issue("entry.actual", "warning", "number — нет факта, нечего дозаполнять", str(actual)))
        if actual is not None and _is_num(actual):
            if flw != 0:
                entry["error_pct"] = round((actual - flw) / flw * 100, 4)
            pp = entry.get("p10_p90")
            if isinstance(pp, list) and len(pp) == 2 and _is_num(pp[0]) and _is_num(pp[1]):
                entry["in_p10_p90"] = bool(pp[0] <= actual <= pp[1])
    elif kind == "event":
        pp = entry.get("predicted_p")
        if entry.get("resolved") is not None and not (_is_num(pp) and 0 <= pp <= 1):
            issues.append(_issue("entry.predicted_p", "blocking",
                                 "нет замороженной вероятности события — исход записывать нельзя; resolved оставлен null",
                                 None if pp is None else str(pp)))
            entry["resolved"] = None
    else:
        issues.append(_issue("entry.kind", "blocking", f"one of {sorted(VALID_OUTCOME_KIND)}", str(kind)))

    _validate_outcome_log_entry(entry, "entry", issues)
    return {"entry": entry, "issues": issues, "blocking_count": len(_blocking(issues))}


def freeze_outcome_log(data: dict) -> dict:
    """Helper: собрать stub outcome_log из fca_stats (заморозка на момент прогноза).

    Вход: {"fca_stats_entry": {...}, "resolve_date", "logged_at", "record_type",
    "confidence_at_forecast", "kind"?}. `kind` берётся из fca_stats_entry, если не задан явно.
    Возвращает stub с actual/resolved = null (заполнит резолв). Копирует, не сочиняет:
    отсутствующие в fca_stats поля переносятся как null (events-yaml-spec.md §14.4).
    """
    fs = data.get("fca_stats_entry") or {}
    issues: list[dict] = []
    kind = data.get("kind") or fs.get("kind")

    entry: dict = {
        "resolve_date": data.get("resolve_date"),
        "logged_at": data.get("logged_at"),
        "record_type": data.get("record_type"),
        "kind": kind,
    }
    if kind == "level":
        entry["forecast_l1_weighted"] = fs.get("l1_weighted")
        entry["forecast_l1_unweighted"] = fs.get("l1_unweighted")
        entry["forecast_l2_ev"] = fs.get("l2_ev")
        p10, p90 = fs.get("p10"), fs.get("p90")
        entry["p10_p90"] = [p10, p90] if (p10 is not None and p90 is not None) else None
        entry["confidence_at_forecast"] = data.get("confidence_at_forecast")
        entry["actual"] = None
        entry["in_p10_p90"] = None
        entry["error_pct"] = None
    elif kind == "event":
        entry["predicted_p"] = fs.get("predicted_p")
        entry["confidence_at_forecast"] = data.get("confidence_at_forecast")
        entry["resolved"] = None
    else:
        issues.append(_issue("kind", "blocking", f"one of {sorted(VALID_OUTCOME_KIND)}", str(kind)))
        entry["confidence_at_forecast"] = data.get("confidence_at_forecast")
    entry["actual_source"] = None
    entry["shock_flag"] = "none"

    _validate_outcome_log_entry(entry, "entry", issues)
    return {"entry": entry, "issues": issues, "blocking_count": len(_blocking(issues))}


def _cone_eps(anchor: float, override=None) -> float:
    if override is not None and _is_num(override):
        return abs(float(override))
    return max(CONE_EPS_REL * abs(anchor), CONE_EPS_ABS_FLOOR)


def compute_cone(by_scenario: dict, anchor, horizons=None, eps=None) -> dict:
    """Детерминированный чек одностороннего конуса (events-yaml-spec.md §15).

    Per-horizon: sign(central_X − anchor) по A/B/C/D; мир нейтрален при |diff| ≤ eps.
    Все ненейтральные по одну сторону → горизонт односторонний. `anchor` — число или
    dict {horizon: число} (per-horizon). Reasoning отсутствует — чистая арифметика.
    """
    by_scenario = by_scenario or {}
    anchor_is_map = isinstance(anchor, dict)

    if horizons is None:
        hz: set = set()
        for sid in ("A", "B", "C", "D"):
            vals = ((by_scenario.get(sid) or {}).get("values")) or {}
            hz.update(vals.keys())
        horizons = sorted(hz)

    cone_side: dict = {}
    horizons_flagged: list = []
    neutral_worlds: dict = {}

    for h in horizons:
        anchor_h = anchor.get(h) if anchor_is_map else anchor
        if not _is_num(anchor_h):
            continue
        diffs = {}
        for sid in ("A", "B", "C", "D"):
            vals = ((by_scenario.get(sid) or {}).get("values")) or {}
            cell = vals.get(h)
            if isinstance(cell, dict) and _is_num(cell.get("central")):
                diffs[sid] = cell["central"] - anchor_h
        if not diffs:
            continue
        eps_h = _cone_eps(anchor_h, eps)
        sides = {sid: ("up" if d > eps_h else "down" if d < -eps_h else "neutral")
                 for sid, d in diffs.items()}
        neutral_worlds[h] = sorted(sid for sid, s in sides.items() if s == "neutral")
        non_neutral = {sid: s for sid, s in sides.items() if s != "neutral"}
        if not non_neutral:
            cone_side[h] = "neutral"
        else:
            distinct = set(non_neutral.values())
            if len(distinct) == 1:
                cone_side[h] = next(iter(distinct))
                horizons_flagged.append(h)
            else:
                cone_side[h] = "two_sided"

    return {
        "one_sided_cone": len(horizons_flagged) > 0,
        "cone_side": cone_side,
        "horizons_flagged": horizons_flagged,
        "neutral_worlds": neutral_worlds,
        "anchor": anchor,
    }


def check_one_sided_cone(data: dict) -> dict:
    """CLI: {"by_scenario": {...}, "anchor": <num|{h:num}>, "horizons"?: [...], "eps"?: <num>}."""
    anchor = data.get("anchor")
    if not (_is_num(anchor) or isinstance(anchor, dict)):
        return {"error": "anchor должен быть числом (текущий факт, НЕ L1) или {horizon: число}"}
    return compute_cone(data.get("by_scenario") or {}, anchor,
                        data.get("horizons"), data.get("eps"))


def _extract_fact_anchor(fa: dict, issues: list):
    """Возвращает anchor (число или {h: число}) из блока fact_anchor, либо None + issues."""
    if not isinstance(fa, dict):
        issues.append(_issue("conditional_on_scenarios.fact_anchor", "blocking",
                             "dict {value, as_of, source}", type(fa).__name__))
        return None
    if isinstance(fa.get("by_horizon"), dict):
        anchor = {}
        for h, sub in fa["by_horizon"].items():
            v = (sub or {}).get("value")
            if _is_num(v):
                anchor[h] = v
            else:
                issues.append(_issue(f"conditional_on_scenarios.fact_anchor.by_horizon.{h}.value",
                                     "blocking", "number (текущий факт)", str(v)))
        return anchor or None
    v = fa.get("value")
    if not _is_num(v):
        issues.append(_issue("conditional_on_scenarios.fact_anchor.value", "blocking",
                             "number (текущий факт, не L1)", str(v)))
        return None
    as_of = fa.get("as_of")
    if not as_of:
        issues.append(_issue("conditional_on_scenarios.fact_anchor.as_of", "warning",
                             "дата факта YYYY-MM-DD (staleness — §15/F6)", None))
    elif not _DATE_RE.match(str(as_of)):
        issues.append(_issue("conditional_on_scenarios.fact_anchor.as_of", "warning",
                             "YYYY-MM-DD", str(as_of)))
    if not fa.get("source"):
        issues.append(_issue("conditional_on_scenarios.fact_anchor.source", "warning",
                             "источник факта (URL/издание/тикер)", None))
    return v


def _validate_cone(data: dict, issues: list) -> None:
    """Гейт одностороннего конуса (events-yaml-spec.md §15.4). Только при conditional-блоке."""
    cond = data.get("conditional_on_scenarios")
    if not isinstance(cond, dict):
        return

    # Типы аддитивных полей.
    cs = cond.get("cone_side")
    if isinstance(cs, dict):
        for h, v in cs.items():
            if v not in VALID_CONE_SIDE:
                issues.append(_issue(f"conditional_on_scenarios.cone_side.{h}", "blocking",
                                     f"one of {sorted(VALID_CONE_SIDE)}", str(v)))
    osc = cond.get("one_sided_cone")
    if osc is not None and not isinstance(osc, bool):
        issues.append(_issue("conditional_on_scenarios.one_sided_cone", "blocking",
                             "bool or absent", str(osc)))
    cwr = cond.get("counter_world_reason")
    if cwr is not None and not isinstance(cwr, str):
        issues.append(_issue("conditional_on_scenarios.counter_world_reason", "blocking",
                             "string or null", str(cwr)))

    fa = cond.get("fact_anchor")
    if fa is None:
        issues.append(_issue("conditional_on_scenarios.fact_anchor", "warning",
                             "текущий факт для cone-чека (§15); без него чек пропущен", None))
        return
    anchor = _extract_fact_anchor(fa, issues)
    if anchor is None:
        return

    res = compute_cone(cond.get("by_scenario") or {}, anchor)

    if res["one_sided_cone"]:
        if not cwr:
            sides = ", ".join(f"{h}:{res['cone_side'][h]}" for h in res["horizons_flagged"])
            issues.append(_issue(
                "conditional_on_scenarios.counter_world_reason", "blocking",
                f"non-empty (§15): встречный мир в by_scenario ИЛИ обоснование. "
                f"Односторонние горизонты — {sides}",
                None))
        if osc is not None and osc is not True:
            issues.append(_issue("conditional_on_scenarios.one_sided_cone", "warning",
                                 "true (пересчёт §15) — расходится с персистированным", str(osc)))
    else:
        if osc is True:
            issues.append(_issue("conditional_on_scenarios.one_sided_cone", "warning",
                                 "false (пересчёт §15) — персистировано true (drift)", str(osc)))


def _validate_falsifier_sides(data: dict, issues: list) -> None:
    """Покрытие falsifiers/monitoring по сторонам (events-yaml-spec.md §15.5). Warning-only."""
    if not isinstance(data.get("conditional_on_scenarios"), dict):
        return
    entries = []
    for key in ("falsifiers", "monitoring"):
        val = data.get(key)
        if isinstance(val, list):
            entries.extend(e for e in val if isinstance(e, dict))
    if not entries:
        return
    for e in entries:
        side = e.get("side")
        if side is not None and side not in VALID_FALSIFIER_SIDE:
            issues.append(_issue(f"{'falsifier/monitoring'}.side", "blocking",
                                 f"one of {sorted(VALID_FALSIFIER_SIDE)}", str(side)))
    sided = [e["side"] for e in entries if e.get("side") in VALID_FALSIFIER_SIDE]
    if not sided:
        issues.append(_issue("falsifiers/monitoring.side", "warning",
                             "сторона не размечена — покрытие сторон не проверено (авто-классификация "
                             "текста = reasoning, запрещено; проставь side вручную)", None))
        return
    covered_up = any(s in ("up", "both") for s in sided)
    covered_down = any(s in ("down", "both") for s in sided)
    missing = [s for s, ok in (("up", covered_up), ("down", covered_down)) if not ok]
    if missing:
        issues.append(_issue("falsifiers/monitoring.side", "warning",
                             f"missing_side_falsifier: нет falsifier/monitor на сторону(ы) {missing}", None))


def _iter_coherence_severities(data: dict) -> list:
    """Собрать все severity из coherence_diagnostic (top-level и nested в conditional,
    флэт и per-horizon/by_horizon формы) — для F5-проверки тавтологичного LOW."""
    out: list = []
    candidates = [data.get("coherence_diagnostic")]
    cond = data.get("conditional_on_scenarios")
    if isinstance(cond, dict):
        candidates.append(cond.get("coherence_diagnostic"))
    for coh in candidates:
        if not isinstance(coh, dict):
            continue
        if isinstance(coh.get("severity"), str):
            out.append(coh["severity"])
        for v in coh.values():
            if isinstance(v, dict) and isinstance(v.get("severity"), str):
                out.append(v["severity"])
        bh = coh.get("by_horizon")
        if isinstance(bh, dict):
            for v in bh.values():
                if isinstance(v, dict) and isinstance(v.get("severity"), str):
                    out.append(v["severity"])
    return out


def _validate_l2_informative(data: dict, issues: list) -> None:
    """F5 (events-yaml-spec.md §18, warning-only): если весь by_scenario DERIVED из marginal,
    L2 не несёт информации — l2_informative:false, coherence N/A, а не LOW 0.0% (тавтология,
    self-audit №4б: диагностика перестала быть измерением)."""
    cond = data.get("conditional_on_scenarios")
    if not isinstance(cond, dict):
        return
    by_scenario = cond.get("by_scenario")
    if not isinstance(by_scenario, dict):
        return
    present = [by_scenario.get(k) for k in ("A", "B", "C", "D") if isinstance(by_scenario.get(k), dict)]
    if len(present) < 4:
        return
    all_derived = all(e.get("provenance") == "derived_from_marginal" for e in present)

    l2_inf = cond.get("l2_informative")
    if l2_inf is not None and not isinstance(l2_inf, bool):
        issues.append(_issue("conditional_on_scenarios.l2_informative", "warning",
                             "bool or absent", str(l2_inf)))
        l2_inf = None

    if all_derived:
        if l2_inf is not False:
            issues.append(_issue("conditional_on_scenarios.l2_informative", "warning",
                                 "весь by_scenario DERIVED → задай l2_informative:false "
                                 "(L2 не несёт информации; coherence N/A, не LOW 0.0%)", str(l2_inf)))
        for sev in _iter_coherence_severities(data):
            if sev == "LOW":
                issues.append(_issue("coherence_diagnostic.severity", "warning",
                                     "0.0% coherence тавтологична при полном DERIVED — репортить N/A, "
                                     "не трактовать LOW как согласованность (§18)", sev))
                break
    elif l2_inf is False:
        issues.append(_issue("conditional_on_scenarios.l2_informative", "warning",
                             "l2_informative:false, но есть native by_scenario (провенанс не DERIVED)",
                             None))


def _validate_deferred_audit(data: dict, issues: list) -> None:
    """§19 (аддитивно, warning-only): final_audit.status: deferred требует scheduled_for (дата)."""
    fa = data.get("final_audit")
    if not isinstance(fa, dict) or fa.get("status") != "deferred":
        return
    sf = fa.get("scheduled_for")
    if not sf:
        issues.append(_issue("final_audit.scheduled_for", "warning",
                             "дата — status: deferred требует scheduled_for (§19)", None))
    elif not _DATE_RE.match(str(sf)):
        issues.append(_issue("final_audit.scheduled_for", "warning", "YYYY-MM-DD", str(sf)))


def _validate_confidence_layering(data: dict, issues: list) -> None:
    """F3 (events-yaml-spec.md §16, аддитивно, warning-only): source_coverage_score +
    confidence_by_horizon. Скаляр forecast.confidence НЕ трогается (legacy, нулевой дрейф)."""
    fc = data.get("forecast")
    if not isinstance(fc, dict):
        return
    scs = fc.get("source_coverage_score")
    if scs is not None and (not _is_num(scs) or not (0 <= scs <= 1)):
        issues.append(_issue("forecast.source_coverage_score", "warning", "число 0..1", str(scs)))
    cbh = fc.get("confidence_by_horizon")
    if cbh is None:
        return
    if not isinstance(cbh, dict):
        issues.append(_issue("forecast.confidence_by_horizon", "warning",
                             "dict {horizon: 0..1}", type(cbh).__name__))
        return
    for h, v in cbh.items():
        if not _is_num(v) or not (0 <= v <= 1):
            issues.append(_issue(f"forecast.confidence_by_horizon.{h}", "warning",
                                 "число 0..1", str(v)))


VALID_CLOSED_BY = {"owner_close", "retro_audit"}


def _validate_closed_forecast(data: dict, issues: list) -> None:
    """Закрытие по факту (references/close-forecast.md): `status: resolved` держится на исходе.

    `final_audit.closed_by` ∈ {owner_close, retro_audit}. `owner_close` без записи
    `horizon_resolve` с фактом — blocking (закрытие без ретро-аудита обязано нести исход);
    `resolved` без такой записи в остальных путях — warning (легаси ретро-аудита).
    """
    if data.get("status") != "resolved":
        return
    fa = data.get("final_audit")
    closed_by = fa.get("closed_by") if isinstance(fa, dict) else None
    if closed_by is not None and closed_by not in VALID_CLOSED_BY:
        issues.append(_issue("final_audit.closed_by", "warning",
                             f"one of {sorted(VALID_CLOSED_BY)}", str(closed_by)))
    log = data.get("outcome_log")
    has_outcome = isinstance(log, list) and any(
        isinstance(e, dict) and e.get("record_type") == "horizon_resolve"
        and (e.get("actual") is not None or e.get("resolved") is not None)
        for e in log)
    if not has_outcome:
        sev = "blocking" if closed_by == "owner_close" else "warning"
        issues.append(_issue("outcome_log", sev,
                             "status: resolved требует outcome_log с record_type: horizon_resolve и фактом "
                             "(actual для level / resolved для event)", None))


def validate_forecast_events(data: dict) -> dict:
    """Validate forecast events YAML — Type 1 (isolated) vs Type 2 (conditional_on_scenarios).

    Spec: events-yaml-spec.md §5. Mutual exclusion: либо `isolated: true`, либо
    `conditional_on_scenarios` блок. Без обоих — blocking.
    """
    issues: list[dict] = []

    # Аддитивные калибровочные блоки (events-yaml-spec.md §14) — валидируются всегда,
    # независимо от Type 1/Type 2 и ранних return ниже. Отсутствие блоков — не ошибка.
    _validate_fca_stats(data, issues)
    _validate_outcome_log(data, issues)
    # Односторонний сценарный конус (events-yaml-spec.md §15, F1) — гейт + покрытие сторон.
    _validate_cone(data, issues)
    _validate_falsifier_sides(data, issues)
    # Расслоение confidence (events-yaml-spec.md §16, F3) — warning-only, скаляр не трогаем.
    _validate_confidence_layering(data, issues)
    # L2-информативность (events-yaml-spec.md §18, F5) — warning-only, DERIVED → не LOW 0.0%.
    _validate_l2_informative(data, issues)
    # Отложенный ретро-аудит (events-yaml-spec.md §19) — deferred требует scheduled_for.
    _validate_deferred_audit(data, issues)
    # Закрытие по факту (references/close-forecast.md) — resolved держится на исходе.
    _validate_closed_forecast(data, issues)

    has_conditional = "conditional_on_scenarios" in data and data["conditional_on_scenarios"] is not None
    is_isolated = bool(data.get("isolated"))

    if not has_conditional and not is_isolated:
        issues.append({
            "field": "isolated|conditional_on_scenarios",
            "severity": "blocking",
            "expected": "either isolated: true OR conditional_on_scenarios block (events-yaml-spec.md §5)",
            "actual": "neither present",
        })

    if has_conditional and is_isolated:
        issues.append({
            "field": "isolated",
            "severity": "blocking",
            "expected": "isolated: true mutually exclusive with conditional_on_scenarios",
            "actual": "both present",
        })

    if is_isolated:
        reason = data.get("isolated_reason")
        if not reason or not isinstance(reason, str):
            issues.append({
                "field": "isolated_reason",
                "severity": "blocking",
                "expected": "non-empty string ≤200 chars (events-yaml-spec.md §5.5)",
                "actual": str(reason),
            })
        elif len(reason) > 200:
            issues.append({
                "field": "isolated_reason",
                "severity": "blocking",
                "expected": "string ≤200 chars",
                "actual": f"{len(reason)} chars",
            })

    if has_conditional:
        # Type 2 conditional требует обязательно Layer 1 marginal (forecast.central_estimate).
        # Это нужно для ru-portfolio-advisor и weekly-review EV (см. CLAUDE.md «Двухслойная архитектура»).
        forecast_block = data.get("forecast") or {}
        if not forecast_block.get("central_estimate"):
            issues.append({
                "field": "forecast.central_estimate",
                "severity": "blocking",
                "expected": "non-empty Layer 1 marginal — Type 2 conditional forecast обязан иметь forecast.central_estimate (для ru-portfolio-advisor); events-yaml-spec.md §5",
                "actual": "missing or empty",
            })

        cond = data["conditional_on_scenarios"]
        if not isinstance(cond, dict):
            issues.append({
                "field": "conditional_on_scenarios",
                "severity": "blocking",
                "expected": "dict",
                "actual": type(cond).__name__,
            })
            return {"valid": False, "blocking_count": len(_blocking(issues)), "issues": issues}

        for field in ("source_matrix", "unit", "by_scenario", "marginal"):
            if cond.get(field) is None:
                issues.append({
                    "field": f"conditional_on_scenarios.{field}",
                    "severity": "blocking",
                    "expected": "present",
                    "actual": None,
                })

        source_matrix = cond.get("source_matrix")
        if source_matrix and not (isinstance(source_matrix, str) and source_matrix.startswith("scenarios/")):
            issues.append({
                "field": "conditional_on_scenarios.source_matrix",
                "severity": "blocking",
                "expected": "string starting with 'scenarios/'",
                "actual": str(source_matrix),
            })

        block_unit = cond.get("unit")

        # FCA-2 strict-режим: opt-in флаг в payload ({"_strict": true}) — включает
        # FCA перед сохранением НОВОГО артефакта. Живые файлы валидируются мягко
        # (кросс-правила §5.2.1 → warning), новые эмиты — жёстко (→ blocking).
        strict_mode = bool(data.get("_strict"))
        if strict_mode and "coherence_diagnostic" in cond:
            issues.append({
                "field": "conditional_on_scenarios.coherence_diagnostic",
                "severity": "blocking",
                "expected": "coherence_diagnostic на top-level forecast YAML (§5.1)",
                "actual": "вложен в conditional_on_scenarios (non-spec форма FCA)",
            })

        by_scenario = cond.get("by_scenario") or {}
        if isinstance(by_scenario, dict):
            present_keys = set(by_scenario.keys())
            missing = REQUIRED_BY_SCENARIO_KEYS - present_keys
            if missing:
                issues.append({
                    "field": "conditional_on_scenarios.by_scenario",
                    "severity": "blocking",
                    "expected": "all 4 keys A, B, C, D (events-yaml-spec.md §5.3)",
                    "actual": f"missing: {sorted(missing)}",
                })
            extra = present_keys - REQUIRED_BY_SCENARIO_KEYS
            if extra:
                issues.append({
                    "field": "conditional_on_scenarios.by_scenario",
                    "severity": "blocking",
                    "expected": "only A, B, C, D",
                    "actual": f"unexpected: {sorted(extra)}",
                })

            for sid in sorted(REQUIRED_BY_SCENARIO_KEYS & present_keys):
                entry = by_scenario.get(sid) or {}
                if not isinstance(entry, dict):
                    issues.append({
                        "field": f"conditional_on_scenarios.by_scenario.{sid}",
                        "severity": "blocking",
                        "expected": "dict",
                        "actual": type(entry).__name__,
                    })
                    continue

                provenance = entry.get("provenance")
                if provenance not in VALID_PROVENANCE:
                    if provenance in LEGACY_PROVENANCE_MAP:
                        actual_msg = (
                            f"legacy '{provenance}' → мигрируй в "
                            f"'{LEGACY_PROVENANCE_MAP[provenance]}' (events-yaml-spec.md §5.2.1)"
                        )
                    else:
                        actual_msg = str(provenance)
                    issues.append({
                        "field": f"conditional_on_scenarios.by_scenario.{sid}.provenance",
                        "severity": "blocking",
                        "expected": f"one of {sorted(VALID_PROVENANCE)}",
                        "actual": actual_msg,
                    })

                # ── FCA-3: upstream_used shape + кросс-правила provenance ↔ спутники ──
                # Кросс-правила: warning в обычном режиме, blocking при {"_strict": true}
                # (FCA включает strict перед сохранением НОВОГО артефакта — SKILL Шаг 6).
                cross_sev = "blocking" if strict_mode else "warning"
                upstream = entry.get("upstream_used")
                if upstream is not None:
                    bad_shape = not isinstance(upstream, list) or any(
                        not isinstance(u, dict) for u in upstream
                    )
                    if bad_shape:
                        issues.append({
                            "field": f"conditional_on_scenarios.by_scenario.{sid}.upstream_used",
                            "severity": "blocking",
                            "expected": "list of {factor, value, unit?, source_file?} (§5.2.1)",
                            "actual": type(upstream).__name__,
                        })
                    else:
                        for ui, u in enumerate(upstream):
                            if not isinstance(u.get("factor"), str) or not u.get("factor"):
                                issues.append({
                                    "field": f"conditional_on_scenarios.by_scenario.{sid}.upstream_used[{ui}].factor",
                                    "severity": "blocking",
                                    "expected": "non-empty string",
                                    "actual": str(u.get("factor")),
                                })
                            uv = u.get("value")
                            if isinstance(uv, bool) or not isinstance(uv, (int, float)):
                                issues.append({
                                    "field": f"conditional_on_scenarios.by_scenario.{sid}.upstream_used[{ui}].value",
                                    "severity": "blocking",
                                    "expected": "number",
                                    "actual": str(uv),
                                })

                sources = entry.get("sources_used")
                if provenance in _PROVENANCE_NEEDS_SOURCES:
                    if not (isinstance(sources, list) and len(sources) > 0):
                        issues.append({
                            "field": f"conditional_on_scenarios.by_scenario.{sid}.sources_used",
                            "severity": cross_sev,
                            "expected": (
                                f"непустой список объектов при provenance: {provenance} (§5.2.1)"
                            ),
                            "actual": f"{type(sources).__name__}: {sources!r}"[:120],
                        })
                elif provenance == "derived_from_upstream":
                    if not (isinstance(upstream, list) and len(upstream) > 0):
                        issues.append({
                            "field": f"conditional_on_scenarios.by_scenario.{sid}.upstream_used",
                            "severity": cross_sev,
                            "expected": "непустой upstream_used при provenance: derived_from_upstream (§5.2.1)",
                            "actual": str(type(upstream).__name__ if upstream is not None else None),
                        })

                # ── FCA-2 strict: известные non-spec формы FCA-вывода ──
                if strict_mode:
                    horizon_keys = [k for k in entry if re.match(r"horizon_\d{4}$", str(k))]
                    if horizon_keys:
                        issues.append({
                            "field": f"conditional_on_scenarios.by_scenario.{sid}",
                            "severity": "blocking",
                            "expected": 'values: {"YYYY-MM-DD": {central, range}} (§5.1)',
                            "actual": f"non-spec ключи {horizon_keys}",
                        })
                    # bool исключён явно (bool — подкласс int): зеркало fca_output_checks,
                    # иначе pre-save гейт FCA и strict-save расходятся (аудит 2026-08-03)
                    if isinstance(sources, int) and not isinstance(sources, bool):
                        issues.append({
                            "field": f"conditional_on_scenarios.by_scenario.{sid}.sources_used",
                            "severity": "blocking",
                            "expected": "список объектов {source_id, camp_weight, reasoning} (§5.2)",
                            "actual": f"число {sources} (детали не в sources_used_detail)",
                        })
                    vals = entry.get("values")
                    if isinstance(vals, dict):
                        for hk, hv in vals.items():
                            if not isinstance(hv, dict):
                                continue
                            if "central_estimate" in hv or "p10" in hv or "p90" in hv:
                                issues.append({
                                    "field": f"conditional_on_scenarios.by_scenario.{sid}.values.{hk}",
                                    "severity": "blocking",
                                    "expected": "{central, range: [lo, hi]} (§5.1)",
                                    "actual": f"non-spec ключи {sorted(set(hv) & {'central_estimate', 'p10', 'p90'})}",
                                })
                            if "unit" in hv:
                                issues.append({
                                    "field": f"conditional_on_scenarios.by_scenario.{sid}.values.{hk}.unit",
                                    "severity": "blocking",
                                    "expected": "unit один на блок conditional_on_scenarios (§5.2)",
                                    "actual": "unit внутри значения горизонта",
                                })

                coverage = entry.get("coverage_quality")
                if coverage not in VALID_COVERAGE_QUALITY:
                    issues.append({
                        "field": f"conditional_on_scenarios.by_scenario.{sid}.coverage_quality",
                        "severity": "blocking",
                        "expected": f"one of {sorted(VALID_COVERAGE_QUALITY)}",
                        "actual": str(coverage),
                    })

                if entry.get("values") is None:
                    issues.append({
                        "field": f"conditional_on_scenarios.by_scenario.{sid}.values",
                        "severity": "blocking",
                        "expected": "dict {horizon: {central, range}}",
                        "actual": None,
                    })

                # Per-scenario unit, if present, must match block-level unit.
                entry_unit = entry.get("unit")
                if entry_unit is not None and block_unit is not None and entry_unit != block_unit:
                    issues.append({
                        "field": f"conditional_on_scenarios.by_scenario.{sid}.unit",
                        "severity": "blocking",
                        "expected": f"matches conditional_on_scenarios.unit ({block_unit!r})",
                        "actual": str(entry_unit),
                    })
        else:
            issues.append({
                "field": "conditional_on_scenarios.by_scenario",
                "severity": "blocking",
                "expected": "dict with keys A, B, C, D",
                "actual": type(by_scenario).__name__,
            })

        marginal = cond.get("marginal") or {}
        if isinstance(marginal, dict):
            method = marginal.get("method")
            if method not in VALID_MARGINAL_METHOD:
                issues.append({
                    "field": "conditional_on_scenarios.marginal.method",
                    "severity": "blocking",
                    "expected": f"one of {sorted(VALID_MARGINAL_METHOD)}",
                    "actual": str(method),
                })
            modal = marginal.get("modal_scenario_id")
            if modal is not None and modal not in VALID_MODAL_SCENARIO:
                issues.append({
                    "field": "conditional_on_scenarios.marginal.modal_scenario_id",
                    "severity": "blocking",
                    "expected": f"one of {sorted(VALID_MODAL_SCENARIO)}",
                    "actual": str(modal),
                })
            marginal_unit = marginal.get("unit")
            if marginal_unit is not None and block_unit is not None and marginal_unit != block_unit:
                issues.append({
                    "field": "conditional_on_scenarios.marginal.unit",
                    "severity": "blocking",
                    "expected": f"matches conditional_on_scenarios.unit ({block_unit!r})",
                    "actual": str(marginal_unit),
                })

        coherence = data.get("coherence_diagnostic")
        if isinstance(coherence, dict):
            severity = coherence.get("severity")
            if severity not in VALID_COHERENCE_SEVERITY:
                issues.append({
                    "field": "coherence_diagnostic.severity",
                    "severity": "blocking",
                    "expected": f"one of {sorted(VALID_COHERENCE_SEVERITY)}",
                    "actual": str(severity),
                })
            div = coherence.get("divergence_pct")
            if div is not None:
                try:
                    div_val = float(div)
                    if div_val < 0:
                        issues.append({
                            "field": "coherence_diagnostic.divergence_pct",
                            "severity": "blocking",
                            "expected": "≥ 0",
                            "actual": str(div),
                        })
                    # Severity threshold check (events-yaml-spec.md §5.2):
                    # LOW <5%, MEDIUM 5–15%, HIGH >15%
                    if severity == "LOW" and div_val >= 5:
                        issues.append({
                            "field": "coherence_diagnostic.severity",
                            "severity": "blocking",
                            "expected": "MEDIUM (5–15%) or HIGH (>15%)",
                            "actual": f"LOW with divergence_pct={div_val}",
                        })
                    elif severity == "MEDIUM" and (div_val < 5 or div_val > 15):
                        issues.append({
                            "field": "coherence_diagnostic.severity",
                            "severity": "blocking",
                            "expected": "LOW (<5%) or HIGH (>15%)",
                            "actual": f"MEDIUM with divergence_pct={div_val}",
                        })
                    elif severity == "HIGH" and div_val <= 15:
                        issues.append({
                            "field": "coherence_diagnostic.severity",
                            "severity": "blocking",
                            "expected": "LOW (<5%) or MEDIUM (5–15%)",
                            "actual": f"HIGH with divergence_pct={div_val}",
                        })
                except (TypeError, ValueError):
                    issues.append({
                        "field": "coherence_diagnostic.divergence_pct",
                        "severity": "blocking",
                        "expected": "numeric",
                        "actual": str(div),
                    })

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

# Валидаторы целевой схемы (schema.md §3.1, §4.3) — модуль ds_schemas (канон в _shared-references/, в .skill —
# в scripts/ рядом: pack.sh кладёт его по импорту вместе с codelists/conditions_merge/time_msk).
import ds_schemas as _ds  # noqa: E402
import time_msk as _time_msk  # noqa: E402

_REPORTS_PREFIX = "Portfolio/reports/"
_FM_SPAN = re.compile(r"\A---\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.S)


_WEEKLY_PREFIX = "Portfolio/weekly-reviews/"
_WEEKLY_NAME = re.compile(r"^weekly-review-(stock|bond)-\d{4}-\d{2}-\d{2}[^/]*\.ya?ml$")
_ITEM_LINE = re.compile(r"^  (['\"]?)([^'\"\s#][^'\"#]*?)\1:\s*(?:#.*)?$")
_PRIO_LINE = re.compile(r"^    verification_priority:.*$")


def _write_replace(path: str, text: str) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _stamp_weekly(root: str, doc: str, path: str, now: str) -> tuple:
    """stamp-report для обзора недели (R28): recorded_at (если нет) и verification_priority каждой бумаги — функцией
    движка в контексте корня (тот же `_priority_context_from_root`, что у валидатора с --root). Правка — построчно
    (строка `    verification_priority:` блока бумаги заменяется или дописывается в конец блока), остальной текст
    не трогается; после правки файл перечитывается и сверяется с ожидаемым — расхождение = ошибка, файл не меняется."""
    import yaml
    with open(path, encoding="utf-8") as f:
        text = f.read()
    data = yaml.safe_load(text)
    ik = "per_stock" if isinstance((data or {}).get("per_stock"), dict) else "per_bond" if isinstance((data or {}).get("per_bond"), dict) else None
    if not isinstance(data, dict) or ik is None:
        return 1, {"ok": False, "error": f"{doc}: не обзор недели — нет per_stock / per_bond"}
    lines = text.split("\n")
    stamped = []
    if data.get("recorded_at") in (None, ""):
        if "recorded_at" in data:
            return 1, {"ok": False, "error": f"{doc}: пустое recorded_at — убрать строку, время ставит скрипт"}
        at = next((i + 1 for i, l in enumerate(lines) if l.startswith("review_date:")), 0)
        lines.insert(at, f'recorded_at: "{now}"')
        data["recorded_at"] = now
        stamped.append("recorded_at")
    for k in ("review_date", "recorded_at"):
        if not isinstance(data.get(k), str) and data.get(k) is not None:
            data[k] = data[k].isoformat() if hasattr(data[k], "isoformat") else str(data[k])
    _priority_context_from_root(data, root)
    ctx = data.get("_priority_context") or {}
    if not ctx:
        return 1, {"ok": False, "error": f"{doc}: контекст приоритета не построен (нет review_date?) — файл не изменён"}
    expected = {}
    for t, e in data[ik].items():
        if isinstance(e, dict):
            x = _expected_priority(e, ctx.get(t) or {})
            if x is None:
                return 1, {"ok": False, "error": "нет constraint_engine — приоритет не посчитать, файл не изменён"}
            expected[str(t)] = x
    # блоки бумаг: от строки «  КЛЮЧ:» до следующей строки с отступом ≤ 2
    try:
        top = next(i for i, l in enumerate(lines) if l.rstrip() == f"{ik}:")
    except StopIteration:
        return 1, {"ok": False, "error": f"{doc}: нет строки «{ik}:» верхнего уровня — файл не изменён"}
    changes, i, n = [], top + 1, len(lines)
    while i < n:
        l = lines[i]
        if l.strip() and not l.startswith((" ", "#")):
            break
        m = _ITEM_LINE.match(l)
        if not m:
            i += 1
            continue
        key, j = m.group(2).strip(), i + 1
        while j < n and (not lines[j].strip() or lines[j].startswith("   ") or lines[j].startswith("#")):
            j += 1
        want = expected.get(key)
        if want is not None:
            pl = next((x for x in range(i + 1, j) if _PRIO_LINE.match(lines[x])), None)
            new = f"    verification_priority: {want}"
            if pl is None:
                end = j
                while end > i + 1 and not lines[end - 1].strip():
                    end -= 1
                lines.insert(end, new)
                n += 1
                j += 1
                changes.append({"key": key, "was": None, "now": want})
            else:
                was = (data[ik].get(key) or {}).get("verification_priority") if isinstance(data[ik].get(key), dict) else None
                if lines[pl] != new:
                    lines[pl] = new
                if was != want:
                    changes.append({"key": key, "was": was, "now": want})
        i = j
    new_text = "\n".join(lines)
    check = yaml.safe_load(new_text)
    got = {str(t): (e or {}).get("verification_priority") for t, e in (check.get(ik) or {}).items() if isinstance(e, dict)}
    if got != expected:
        bad = sorted(k for k in expected if got.get(k) != expected[k])
        return 1, {"ok": False, "error": f"{doc}: построчная правка не дала ожидаемых приоритетов ({', '.join(bad[:5])}) — "
                                         f"файл не изменён"}
    if changes:
        stamped.append("verification_priority")
    if new_text != text:
        _write_replace(path, new_text)
    return 0, {"ok": True, "command": "stamp-report", "doc": doc, "stamped": stamped,
               "recorded_at": data.get("recorded_at"),
               "priority_changed": [f"{c['key']}: {c['was'] or '—'} → {c['now']}" for c in changes],
               "priority": expected}


def stamp_report(argv: list) -> tuple:
    """stamp-report: время записи и версия схемы в шапку отчёта — скриптом, не моделью (schema.md §1 п.4, §4.3).

    Аргументы: --root <корень Claude-Memory> --doc Portfolio/reports/<файл>.md [--now <время, для тестов>].
    Нет recorded_at — дописывается `recorded_at: "<МСК сейчас>"`; нет schema_version — `schema_version: report@1`
    (строки — в конец шапки, тело не трогается). Оба есть — файл не пишется (`stamped: []`). schema_version другой —
    ошибка. Запись — временный файл рядом и os.replace. → (код выхода, объект вывода).

    Обзор недели (R28): --doc Portfolio/weekly-reviews/weekly-review-{stock|bond}-<дата>.yaml — `recorded_at`, если
    его нет, и `verification_priority` каждой бумаги функцией движка (`_stamp_weekly`); в выводе `priority_changed`
    — «тикер: было → стало».
    """
    opts, it = {}, iter(argv)
    for a in it:
        if a in ("--root", "--doc", "--now"):
            opts[a] = next(it, None)
        else:
            return 1, {"ok": False, "error": f"неизвестный аргумент {a!r}; допустимы --root, --doc"}
    root, doc = opts.get("--root"), opts.get("--doc")
    if not root or not doc:
        return 1, {"ok": False, "error": "нужны --root <корень Claude-Memory> и --doc Portfolio/reports/<файл>.md"}
    hub_settings.require_ai(root, "assemble_artifact.py stamp-report", "штамп отчёта", zones=("Portfolio", "scenarios"))   # вход — вывод модели: при «без ИИ» отказ
    if doc.startswith(_WEEKLY_PREFIX) and ".." not in doc.split("/"):
        if not _WEEKLY_NAME.match(doc[len(_WEEKLY_PREFIX):]):
            return 1, {"ok": False, "error": f"--doc: ожидается {_WEEKLY_PREFIX}weekly-review-<stock|bond>-<дата>.yaml, получено {doc!r}"}
        now = opts.get("--now") or _time_msk.now_iso()
        if not _ds.is_time(now):
            return 1, {"ok": False, "error": f"--now: ожидается ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00, получено {now!r}"}
        root_abs = os.path.abspath(os.path.expanduser(root))
        path = os.path.join(root_abs, *doc.split("/"))
        if not os.path.isfile(path):
            return 1, {"ok": False, "error": f"нет обзора {path} — сначала записать файл"}
        return _stamp_weekly(root_abs, doc, path, now)
    if not doc.startswith(_REPORTS_PREFIX) or not doc.endswith(".md") or ".." in doc.split("/"):
        return 1, {"ok": False, "error": f"--doc: ожидается путь от корня вида {_REPORTS_PREFIX}<файл>.md, получено {doc!r}"}
    now = opts.get("--now") or _time_msk.now_iso()
    if not _ds.is_time(now):
        return 1, {"ok": False, "error": f"--now: ожидается ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00, получено {now!r}"}
    path = os.path.join(os.path.abspath(os.path.expanduser(root)), *doc.split("/"))
    if not os.path.isfile(path):
        return 1, {"ok": False, "error": f"нет отчёта {path} — сначала записать файл отчёта"}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = _FM_SPAN.match(text)
    fm = _ds.report_frontmatter(text) if m else None
    if not m or not isinstance(fm, dict):
        return 1, {"ok": False, "error": f"{doc}: нет YAML-шапки (--- … ---) — шапку пишет модель по шаблону отчёта"}
    sv = fm.get("schema_version")
    if sv is not None and sv != _ds.REPORT_SCHEMA_VERSION:
        return 1, {"ok": False, "error": f"{doc}: schema_version {sv!r}, ожидается {_ds.REPORT_SCHEMA_VERSION!r}"}
    add = []
    if sv is None:
        add.append(("schema_version", f"schema_version: {_ds.REPORT_SCHEMA_VERSION}"))
    if fm.get("recorded_at") in (None, ""):
        if "recorded_at" in fm:
            return 1, {"ok": False, "error": f"{doc}: пустое recorded_at в шапке — убрать строку, время ставит скрипт"}
        add.append(("recorded_at", f'recorded_at: "{now}"'))
    if not add:
        return 0, {"ok": True, "command": "stamp-report", "doc": doc, "stamped": [],
                   "recorded_at": fm.get("recorded_at")}
    body_start = m.start(1) if m.group(1) is not None else 4
    inner = m.group(1) or ""
    new_inner = inner + "".join(line + "\n" for _, line in add)
    new_text = text[:body_start] + new_inner + text[body_start + len(inner):]
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    rec = now if any(k == "recorded_at" for k, _ in add) else fm.get("recorded_at")
    return 0, {"ok": True, "command": "stamp-report", "doc": doc, "stamped": [k for k, _ in add], "recorded_at": rec}


def _ds_issues(errors: list) -> dict:
    """Строки ошибок ds_schemas («поле: что не так») → формат команд этого скрипта; все блокирующие."""
    issues = []
    for e in errors:
        field, _, what = e.partition(": ")
        issues.append({"field": field, "severity": "blocking", "expected": what or e, "actual": None})
    return {"valid": not issues, "blocking_count": len(issues), "issues": issues}


def validate_decision(data: dict) -> dict:
    """validate-decision: решение decision@1 (schema.md §3.1) — обёртка над ds_schemas.validate_decision."""
    return _ds_issues(_ds.validate_decision(data))


def validate_report(data: dict) -> dict:
    """validate-report: шапка отчёта report@1 (schema.md §4.3) и блок `decisions:` (поля модели §3.1).

    Блокирующий; единственная проверка шапки Workflow N (N2). Вход — шапка `--file отчёт.md` или JSON-объект шапки.
    """
    return _ds_issues(_ds.validate_report(data))


# ---------------------------------------------------------------------------
# validate-retro-audit-paths (Workflow D — pre-emit checklist)
# ---------------------------------------------------------------------------
#
# Pre-emit guard для Workflow D: проверяет destination paths и имена файлов
# ДО записи в Claude-Memory. Ловит deprecated `_audits/` / `audits/`, suffix
# `-audit` в domains/, MCP-следы (`(N)`, пробелы) и рассинхрон пары.
#
# Input:
#   {
#     "report_path":  "reports/2026-05-15-zhirinovsky-1991-2022.md",   # optional if only=profile
#     "profile_path": "domains/geopolitics/zhirinovsky-1991-2022.md",  # optional if only=report
#     "source_slug":  "zhirinovsky",
#     "period":       "1991-2022",
#     "audit_date":   "2026-05-15",
#     "only":         "report" | "profile" | null
#   }
# Output: {"valid": bool, "blocking_count": int, "issues": [{field, severity, expected, actual}]}

_FORBIDDEN_DEST_RE = re.compile(r"(^|/)_?audits/")
_MCP_DUP_RE = re.compile(r" \(\d+\)(\.|$)")
_REPORT_EXT_RE = re.compile(r"\.(md|docx)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}(-\d{4})?$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _issue(field: str, severity: str, expected, actual) -> dict:
    return {"field": field, "severity": severity, "expected": expected, "actual": actual}


def validate_retro_audit_paths(data: dict) -> dict:
    """Pre-emit path/name validator for Workflow D (retro-audit atomic save)."""
    issues: list[dict] = []

    only = data.get("only")
    if only not in (None, "report", "profile"):
        issues.append(_issue("only", "blocking", "'report' | 'profile' | null", only))

    report_path = data.get("report_path")
    profile_path = data.get("profile_path")
    source_slug = data.get("source_slug")
    period = data.get("period")
    audit_date = data.get("audit_date")

    # Required: source_slug, period, audit_date — always
    for field, val, pat in (
        ("source_slug", source_slug, _SLUG_RE),
        ("period", period, _PERIOD_RE),
        ("audit_date", audit_date, _DATE_RE),
    ):
        if not val:
            issues.append(_issue(field, "blocking", "non-empty", None))
        elif not pat.match(str(val)):
            issues.append(_issue(field, "blocking", pat.pattern, val))

    # Pair requirements depending on `only`
    if only is None:
        if not report_path:
            issues.append(_issue("report_path", "blocking", "non-empty (atomic D requires both files)", None))
        if not profile_path:
            issues.append(_issue("profile_path", "blocking", "non-empty (atomic D requires both files)", None))
    elif only == "report":
        if not report_path:
            issues.append(_issue("report_path", "blocking", "non-empty (only=report)", None))
    elif only == "profile":
        if not profile_path:
            issues.append(_issue("profile_path", "blocking", "non-empty (only=profile)", None))

    # Per-path checks
    def _check_path(path: str, role: str) -> None:
        if not path:
            return
        if _FORBIDDEN_DEST_RE.search(path):
            issues.append(_issue(
                role, "blocking",
                "no '_audits/' or 'audits/' (deprecated) — use 'reports/' for full report and 'domains/{domain}/' for profile",
                path,
            ))
        basename = path.rsplit("/", 1)[-1]
        if _MCP_DUP_RE.search(basename) or " " in basename:
            issues.append(_issue(
                role, "blocking",
                "no spaces or '(N)' in filename (MCP dup marker)",
                basename,
            ))

    _check_path(report_path, "report_path")
    _check_path(profile_path, "profile_path")

    # Report path shape: reports/{audit_date}-{source_slug}-{period}.{md|docx}
    if report_path:
        if not report_path.startswith("reports/"):
            issues.append(_issue(
                "report_path", "blocking",
                "must start with 'reports/'",
                report_path,
            ))
        basename = report_path.rsplit("/", 1)[-1]
        if not _REPORT_EXT_RE.search(basename):
            issues.append(_issue(
                "report_path", "blocking",
                "extension '.md' or '.docx'",
                basename,
            ))
        if audit_date and source_slug and period:
            expected_stem = f"{audit_date}-{source_slug}-{period}"
            stem = _REPORT_EXT_RE.sub("", basename)
            if stem != expected_stem:
                issues.append(_issue(
                    "report_path", "blocking",
                    f"basename stem '{expected_stem}.(md|docx)'",
                    basename,
                ))

    # Profile path shape: domains/{domain}/{source_slug}-{period}.md (NO -audit suffix)
    if profile_path:
        parts = profile_path.split("/")
        if len(parts) != 3 or parts[0] != "domains":
            issues.append(_issue(
                "profile_path", "blocking",
                "must match 'domains/{domain}/{source-slug}-{period}.md'",
                profile_path,
            ))
        else:
            basename = parts[2]
            if not basename.endswith(".md"):
                issues.append(_issue(
                    "profile_path", "blocking",
                    "extension '.md'",
                    basename,
                ))
            stem = basename[:-3] if basename.endswith(".md") else basename
            if stem.endswith("-audit"):
                issues.append(_issue(
                    "profile_path", "blocking",
                    "no '-audit' suffix in profile filename (deprecated convention)",
                    basename,
                ))
            if source_slug and period:
                expected_stem = f"{source_slug}-{period}"
                if stem != expected_stem and not stem.endswith("-audit"):
                    issues.append(_issue(
                        "profile_path", "blocking",
                        f"basename stem '{expected_stem}.md'",
                        basename,
                    ))

    blocking = _blocking(issues)
    return {
        "valid": len(blocking) == 0,
        "blocking_count": len(blocking),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# validate-calibration-report (Workflow O — отчёты калибровки в Claude-Memory/calibration/)
# ---------------------------------------------------------------------------

# kind → жёсткий префикс имени файла. По basename'у считает калибровочный сторож
# forecast-monitor (M1–M4, calibration-playbook.md) — имя не по паттерну = невидимый отчёт.
CALIBRATION_KIND_PREFIX = {
    "adhoc": "adhoc-",                          # ручной ad-hoc прогон (§M1)
    "skill": "calibration-",                    # отчёт будущего calibration-скилла (гасит M2)
    "source_rerating": "source-rerating-",      # пере-рейтинг источников (§M3)
    "catalyst": "catalyst-calibration-",        # catalyst-калибровка v2-C (§M4)
}
_CAL_FILENAME_SUFFIX_RE = re.compile(r"^(-v\d+)?\.md$")


def validate_calibration_report(data: dict) -> dict:
    """Pre-emit валидатор Workflow O: frontmatter + жёсткое имя файла-маркера."""
    issues: list[dict] = []
    fm = data.get("frontmatter") or {}
    filename = data.get("filename") or ""

    if fm.get("type") != "calibration-report":
        issues.append(_issue("frontmatter.type", "blocking", "calibration-report", fm.get("type")))

    kind = fm.get("kind")
    if kind not in CALIBRATION_KIND_PREFIX:
        issues.append(_issue("frontmatter.kind", "blocking",
                             sorted(CALIBRATION_KIND_PREFIX), kind))

    date_val = fm.get("date")
    if not (isinstance(date_val, str) and _DATE_RE.match(date_val)):
        issues.append(_issue("frontmatter.date", "blocking", "YYYY-MM-DD (строкой)", date_val))

    summary = fm.get("summary")
    if not (isinstance(summary, str) and summary.strip()):
        issues.append(_issue("frontmatter.summary", "blocking",
                             "1-2 предложения (нужен для INDEX)", summary))

    n_clean = fm.get("n_clean")
    if n_clean is None:
        issues.append(_issue("frontmatter.n_clean", "warning",
                             "размер зачётной выборки (честность метрик при малом n)", None))
    elif not isinstance(n_clean, int) or isinstance(n_clean, bool) or n_clean < 0:
        issues.append(_issue("frontmatter.n_clean", "blocking", "int >= 0", n_clean))

    for key, value in fm.items():
        if isinstance(value, str) and value.startswith("TODO_LLM"):
            issues.append(_issue(f"frontmatter.{key}", "blocking",
                                 "replaced TODO_LLM placeholder", value))

    # Имя файла: {prefix}{date}.md (допустим суффикс -vN при втором прогоне в тот же день)
    if kind in CALIBRATION_KIND_PREFIX and isinstance(date_val, str) and _DATE_RE.match(date_val):
        expected_head = f"{CALIBRATION_KIND_PREFIX[kind]}{date_val}"
        tail = filename[len(expected_head):] if filename.startswith(expected_head) else None
        if tail is None or not _CAL_FILENAME_SUFFIX_RE.match(tail):
            issues.append(_issue(
                "filename", "blocking",
                f"{expected_head}.md (или {expected_head}-vN.md) — по basename считает "
                "калибровочный сторож forecast-monitor",
                filename,
            ))
    if "/" in filename:
        issues.append(_issue("filename", "blocking",
                             "basename без пути (сохранение — только в calibration/)", filename))

    blocking = _blocking(issues)
    return {"valid": len(blocking) == 0, "blocking_count": len(blocking), "issues": issues}


# ---------------------------------------------------------------------------
# validate-monitor-report (Workflow L3, 2026-10-26)
# ---------------------------------------------------------------------------

_MR_SEVERITIES = {"HIGH", "MEDIUM", "LOW", "INFO"}
_MR_CATEGORIES = set(codelists.codes("alert_kind"))
_MR_FRESHNESS = {"integrated_view", "stress", "weekly_review", "macro_snapshot", "trust_matrix"}
# Готовая команда: «/скилл что сделать …». Без имени скилла чат начинает без контекста проекта
# (кейс 2026-10-26: «Условие … — разбираем» → общий разбор облигации с ошибкой в купоне).
_MR_COMMAND_RE = re.compile(r"^/[a-z][a-z0-9:-]*\s+\S")
# Находка по условию (schema.md §3.3, шаг 7): задача hub-notify переносит её в состояние (event_found + fired)
_MR_FINDING_FIELDS = ("condition_id", "version", "doc", "found_at", "note")
# Пункт monitoring[] с прошедшей датой, по которому алерта нет (yaml-schemas §8): строка monitoring_checked
_MR_CHECKED_FIELDS = ("target", "target_file", "monitoring_id", "check_date", "result", "note")
_MR_CHECKED_RESULTS = set(codelists.codes("monitoring_result"))
# Отчёты, собранные раньше этой даты, покрытие пунктов мониторинга не проверяет (старые остаются валидными)
MR_COVERAGE_SINCE = "2026-11-05"


def _monitoring_context_from_root(data, root: str) -> None:
    """`_monitoring_context` для monitor-report: по активным `forecasts/*.yaml` и `scenarios/*.yaml` корня (при
    `scope: partial` — только файлы из `checked`) пункты `monitoring[]` с `check_date` не позже даты `generated_at`
    (`due`) и id пунктов каждого файла (`ids`). Только чтение."""
    if not isinstance(data, dict) or data.get("type") != "monitor-report":
        return
    import glob
    import yaml
    gen = str(data.get("generated_at") or "")[:10]
    root = os.path.abspath(os.path.expanduser(root))
    only = None
    if data.get("scope") == "partial":
        only = {str(c).strip() for c in (data.get("checked") or []) if c}
    due, ids, topics = [], {}, {}
    for folder in ("forecasts", "scenarios"):
        for path in sorted(glob.glob(os.path.join(root, folder, "*.yaml"))):
            rel = f"{folder}/{os.path.basename(path)}"
            if only is not None and rel not in only:
                continue
            try:
                doc = yaml.safe_load(open(path, encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(doc, dict) or doc.get("status") != "active":
                continue
            topic = ((doc.get("forecast") or {}).get("topic") or (doc.get("matrix") or {}).get("topic")
                     or doc.get("topic"))
            topics[rel] = topic
            ids[rel] = []
            for m in doc.get("monitoring") or []:
                if not isinstance(m, dict) or not m.get("id"):
                    continue
                ids[rel].append(str(m["id"]))
                cd = str(m.get("check_date") or "")[:10]
                if _DATE_RE.match(cd) and _DATE_RE.match(gen) and cd <= gen:
                    due.append({"target": topic, "target_file": rel, "monitoring_id": str(m["id"]), "check_date": cd})
    data["_monitoring_context"] = {"due": due, "ids": ids, "topics": topics}


def _mr_covers(row: dict, item: dict, topics: dict) -> bool:
    """Строка отчёта (алерт или monitoring_checked) покрывает пункт: тот же monitoring_id и та же цель
    (target_file или target)."""
    if str(row.get("monitoring_id") or "") != item["monitoring_id"]:
        return False
    tf = str(row.get("target_file") or "").strip()
    return tf == item["target_file"] or (bool(item.get("target")) and row.get("target") == item["target"])


def _validate_monitoring_coverage(data: dict, issues: list) -> None:
    """Пункт monitoring[] с прошедшей датой не может исчезнуть из отчёта: каждый — алерт с monitoring_id или строка
    monitoring_checked; монитор подаёт их заготовкой (`monitor_alerts.py` → `monitoring_checked`). Пункты прогноза,
    по которому в отчёте есть алерт `horizon_passed` (тот же target_file или target), покрыты им: прогноз целиком
    ждёт закрытия с исходом, отдельные строки не нужны."""
    alerts = [a for a in (data.get("alerts") or []) if isinstance(a, dict)]
    checked = data.get("monitoring_checked")
    if checked is not None and not isinstance(checked, list):
        issues.append(_issue("monitoring_checked", "blocking", "список", type(checked).__name__))
        checked = []
    checked = checked or []
    for i, r in enumerate(checked):
        path = f"monitoring_checked[{i}]"
        if not isinstance(r, dict):
            issues.append(_issue(path, "blocking", "объект", type(r).__name__))
            continue
        for k in sorted(set(r) - set(_MR_CHECKED_FIELDS)):
            issues.append(_issue(f"{path}.{k}", "warning", list(_MR_CHECKED_FIELDS), k))
        for k in ("target", "target_file", "monitoring_id", "check_date", "result"):
            if not r.get(k):
                issues.append(_issue(f"{path}.{k}", "blocking", "обязательное поле", r.get(k)))
        if r.get("check_date") and not _DATE_RE.match(str(r["check_date"])):
            issues.append(_issue(f"{path}.check_date", "blocking", "ISO-дата", r["check_date"]))
        res = r.get("result")
        if res and res not in _MR_CHECKED_RESULTS:
            issues.append(_issue(f"{path}.result", "blocking", sorted(_MR_CHECKED_RESULTS), res))
        note = r.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 200):
            issues.append(_issue(f"{path}.note", "warning", "строка ≤ 200 или null", note))
        if res == "unverified" and not (isinstance(note, str) and note.strip()):
            issues.append(_issue(f"{path}.note", "warning", "почему не проверено (ручной пункт, нет данных)", note))

    gen = str(data.get("generated_at") or "")[:10]
    if not _DATE_RE.match(gen) or gen < MR_COVERAGE_SINCE:
        return
    ctx = data.get("_monitoring_context")
    if not isinstance(ctx, dict):
        issues.append(_issue("monitoring_checked", "warning",
                             "контекст не передан, покрытие мониторинга не проверено (запусти с --root <корень Claude-Memory>)",
                             None))
        return
    ids, topics = ctx.get("ids") or {}, ctx.get("topics") or {}
    rows = [("alerts", i, a) for i, a in enumerate(alerts)] + \
           [("monitoring_checked", i, r) for i, r in enumerate(checked) if isinstance(r, dict)]
    for kind, i, r in rows:
        mid = r.get("monitoring_id")
        if not mid:
            continue
        tf = str(r.get("target_file") or "").strip()
        if not tf:
            tf = next((f for f, t in topics.items() if t and t == r.get("target")), "")
        if tf in ids and str(mid) not in ids[tf]:
            issues.append(_issue(f"{kind}[{i}].monitoring_id", "warning",
                                 f"id пункта из monitoring[] {tf}", mid))
    closing = [a for a in alerts if a.get("category") == "horizon_passed"]
    closing_files = {str(a.get("target_file") or "").strip() for a in closing} - {""}
    closing_targets = {a.get("target") for a in closing if a.get("target")}
    for item in ctx.get("due") or []:
        if item["target_file"] in closing_files or (item.get("target") and item["target"] in closing_targets):
            continue
        if not any(_mr_covers(r, item, topics) for _, _, r in rows):
            issues.append(_issue("monitoring_checked", "blocking",
                                 "алерт с monitoring_id или строка monitoring_checked (заготовка — вывод monitor_alerts.py)",
                                 f"пункт мониторинга с прошедшей датой не отражён: {item['target_file']} "
                                 f"{item['monitoring_id']} {item['check_date']}"))


def validate_monitor_report(data: dict) -> dict:
    """monitor-report (forecast-monitor Шаг 7): обязательные поля Workflow L3 и готовая команда
    в suggested_action у HIGH/MEDIUM. Находки по условиям — в condition_findings[], не в alerts;
    прежнее поле condition_events — blocking."""
    issues: list[dict] = []
    for f in ("schema_version", "type", "generated_at", "producer", "alerts", "freshness_audit"):
        if data.get(f) is None:
            issues.append(_issue(f, "blocking", "обязательное поле", None))
    if data.get("type") not in (None, "monitor-report"):
        issues.append(_issue("type", "blocking", "monitor-report", data.get("type")))
    scope = data.get("scope")
    if scope is not None and scope not in ("full", "partial"):
        issues.append(_issue("scope", "warning", "full | partial", scope))
    if scope == "partial":
        ck = data.get("checked")
        if not isinstance(ck, list) or not [c for c in ck if c]:
            issues.append(_issue("checked", "warning",
                                 "список проверенных target_file при scope: partial (иначе вьюер не знает, по каким файлам заменить предупреждения)",
                                 ck))
    fa = data.get("freshness_audit")
    if fa is not None:
        if not isinstance(fa, dict):
            issues.append(_issue("freshness_audit", "blocking", "объект", type(fa).__name__))
        else:
            for k in sorted(set(fa) - _MR_FRESHNESS):
                issues.append(_issue(f"freshness_audit.{k}", "warning", sorted(_MR_FRESHNESS), k))
    alerts = data.get("alerts")
    if alerts is not None and not isinstance(alerts, list):
        issues.append(_issue("alerts", "blocking", "список", type(alerts).__name__))
        alerts = []
    for i, a in enumerate(alerts or []):
        path = f"alerts[{i}]"
        if not isinstance(a, dict):
            issues.append(_issue(path, "blocking", "объект", type(a).__name__))
            continue
        for f in ("severity", "category", "target", "message", "detected_at"):
            if not a.get(f):
                issues.append(_issue(f"{path}.{f}", "blocking", "обязательное поле", a.get(f)))
        sev, cat = a.get("severity"), a.get("category")
        if sev and sev not in _MR_SEVERITIES:
            issues.append(_issue(f"{path}.severity", "blocking", sorted(_MR_SEVERITIES), sev))
        if cat and cat not in _MR_CATEGORIES:
            issues.append(_issue(f"{path}.category", "blocking", sorted(_MR_CATEGORIES), cat))
        if str(a.get("target") or "").startswith("condition") or a.get("target_kind") == "condition":
            issues.append(_issue(f"{path}.target", "blocking",
                                 "событие условия — строка condition_findings (задача hub-notify перенесёт её в состояние условия), не alerts",
                                 a.get("target")))
        if sev in ("HIGH", "MEDIUM"):
            sa = str(a.get("suggested_action") or "").strip().strip("`")
            if not _MR_COMMAND_RE.match(sa):
                issues.append(_issue(f"{path}.suggested_action", "blocking",
                                     "готовая команда «/скилл что сделать id» (как в «Итоге» дайджеста)",
                                     a.get("suggested_action")))
            elif cat == "horizon_passed" and not re.sub(r"^/\S+\s+", "", sa).startswith("Закрой прогноз"):
                issues.append(_issue(f"{path}.suggested_action", "warning",
                                     "«/save-to-library Закрой прогноз <тема>: на <дата> <факт>, прогноз <центр> — сбылся | не сбылся» "
                                     "(горизонт прошёл — закрывают с исходом, не обновляют)",
                                     a.get("suggested_action")))
    if "condition_events" in data:
        issues.append(_issue("condition_events", "blocking",
                             "упразднено: находки по условиям — condition_findings[] {condition_id, version, doc, found_at, note}",
                             "condition_events"))
    cf = data.get("condition_findings")
    if cf is not None:
        if not isinstance(cf, list):
            issues.append(_issue("condition_findings", "blocking", "список", type(cf).__name__))
            cf = []
        for i, r in enumerate(cf):
            path = f"condition_findings[{i}]"
            if not isinstance(r, dict):
                issues.append(_issue(path, "blocking", "объект", type(r).__name__))
                continue
            for k in sorted(set(r) - set(_MR_FINDING_FIELDS)):
                issues.append(_issue(f"{path}.{k}", "blocking", list(_MR_FINDING_FIELDS), k))
            if not isinstance(r.get("condition_id"), str) or not r["condition_id"].strip():
                issues.append(_issue(f"{path}.condition_id", "blocking", "обязательное поле", r.get("condition_id")))
            v = r.get("version")
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                issues.append(_issue(f"{path}.version", "blocking", "целое ≥ 1 (версия определения условия)", v))
            fa, doc = r.get("found_at"), r.get("doc")
            if fa is not None and not _DATE_RE.match(str(fa)):
                issues.append(_issue(f"{path}.found_at", "blocking", "ISO-дата публикации события или null", fa))
            if fa and not (isinstance(doc, str) and doc.strip()):
                issues.append(_issue(f"{path}.doc", "blocking", "ссылка на документ при found_at", doc))
            if doc and not fa:
                issues.append(_issue(f"{path}.found_at", "blocking", "дата при doc (находка без даты не переносится)", fa))
            note = r.get("note")
            if note is not None and (not isinstance(note, str) or len(note) > 200):
                issues.append(_issue(f"{path}.note", "warning", "строка ≤ 200 или null", note))
    _validate_monitoring_coverage(data, issues)
    blocking = _blocking(issues)
    return {"valid": len(blocking) == 0, "blocking_count": len(blocking), "issues": issues}


def validate_macro_scenarios(data: dict) -> dict:
    """Файл макро-цепочки macro-scenarios-<дата>.yaml (Workflow J): сетка дат уровней пяти факторов —
    та же проверка, что у стресса (`macro_grid_check`). Отказы — blocking, расхождение pct_vs_spot — warning.
    Сценарии — из `scenario_matrix.scenarios` файла, иначе по ключам by_scenario (плюс единый набор у факторов)."""
    issues: list[dict] = []
    errs, warns = _macro_grid_check.check_macro_file(data)
    for e in errs:
        issues.append({"field": "macro-scenarios", "severity": "blocking", "expected": "годная сетка дат факторов",
                       "actual": e})
    for w in warns:
        issues.append({"field": "macro-scenarios", "severity": "warning", "expected": "pct_vs_spot согласован с value",
                       "actual": w})
    blocking = _blocking(issues)
    return {"valid": len(blocking) == 0, "blocking_count": len(blocking), "issues": issues}


COMMANDS = {
    "validate-stress": validate_stress,
    "validate-scenario-events": validate_scenario_events,
    "validate-forecast": validate_forecast_frontmatter,
    "validate-forecast-events": validate_forecast_events,
    "validate-audit": validate_audit_frontmatter,
    "validate-weekly-review": validate_weekly_review,
    "validate-weekly-review-stock": validate_weekly_review_stock_detailed,
    "validate-weekly-review-bond": validate_weekly_review_bond_detailed,
    "validate-snapshot": validate_portfolio_snapshot,
    # Workflow J — файл макро-цепочки macro-scenarios-<дата>.yaml: сетка дат факторов (до записи в macro-chain/)
    "validate-macro-scenarios": validate_macro_scenarios,
    # Workflow G — frontmatter integrated-view (контракт @1.3, графики вьюера)
    "validate-integrated-view": validate_integrated_view,
    "check-yaml-duplicates": check_yaml_duplicates,
    "determine-subfolder": lambda d: determine_subfolder(flatten_trust(d.get("trust", {}))),
    "compute-inclusion": lambda d: compute_inclusion(bool(d.get("pin", False)), flatten_trust(d.get("trust", {}))),
    # Цикл машиночитаемости, шаг 8 — решение по бумаге и шапка отчёта (schema.md §3.1, §4.3); блокирующие
    "validate-decision": validate_decision,
    "validate-report": validate_report,
    # METH-1/v1.4 — Constraint carry-over presence check (Workflow F2.6)
    # Workflow D — pre-emit guard для атомарного retro-audit save
    "validate-retro-audit-paths": validate_retro_audit_paths,
    # §14 outcome_log калибровка — детерминированные helper'ы (Workflow B4.6 / L / status-mgmt)
    "freeze-outcome-log": freeze_outcome_log,
    "complete-outcome-log": complete_outcome_log,
    # §15 F1 — детерминированный чек одностороннего конуса (FCA / dry-run приёмки)
    "check-one-sided-cone": check_one_sided_cone,
    # Workflow O — калибровочные отчёты (Claude-Memory/calibration/, маркеры сторожа M1–M4)
    "validate-calibration-report": validate_calibration_report,
    # Workflow L3 — monitor-report: поля + готовая команда в suggested_action (2026-10-26)
    "validate-monitor-report": validate_monitor_report,
}


def _load_doc(path: str):
    """YAML/JSON-файл целиком; у .md — YAML frontmatter. Для --file (RPA-38)."""
    import yaml  # PyYAML — как у остальных скриптов сохранения
    text = open(path, encoding="utf-8").read()
    if path.endswith(".md"):
        if not text.startswith("---"):
            raise ValueError(f"{path}: нет YAML frontmatter")
        end = text.find("\n---", 3)
        text = text[3:end] if end > 0 else ""
    return json.loads(text) if path.endswith(".json") else yaml.safe_load(text)


def _priority_context_from_root(data, root: str) -> None:
    """`_priority_context` для per_stock / per_bond обзора из решений и условий корня (только чтение)."""
    if not isinstance(data, dict):
        return
    ik = "per_stock" if isinstance(data.get("per_stock"), dict) else "per_bond" if isinstance(data.get("per_bond"), dict) else None
    if ik is None:
        return
    import decisions_read as dr  # общий модуль: в .skill — рядом (pack.sh по импорту)
    today = str(data.get("review_date") or "")[:10]
    if not _ds.is_date(today):
        return
    root = os.path.abspath(os.path.expanduser(root))
    items, _ = dr.load(root)
    latest, types, attrs = dr.latest_by_key(items), dr.key_types(root), dr.load_attrs(root)
    rows, _missing = dr.conditions_rows(root, today)
    ctx = {}
    for t in data[ik]:
        e = data[ik][t] if isinstance(data[ik][t], dict) else {}
        row = {"review_date": today, "recorded_at": data.get("recorded_at"), "advisor_verdict": e.get("advisor_verdict"),
               "gate_review_required": (e.get("flags") or {}).get("gate_review_required") is True}
        g = (dr.gate(latest.get(t), today, key=t, decisions=dr.for_key(items, t), reviews=[row], attrs=attrs)
             if dr.key_type(types, t) in ("stock", None) else None)
        ctx[t] = {"gate_status": g["status"] if g else None,
                  "active_condition_verdicts": [r["verdict_on_trigger"] for r in rows
                                                if r["key"] == t and r["active"] and r["verdict_on_trigger"]]}
    data["_priority_context"] = ctx


def _read_input(argv: list[str]):
    """Вход команды: из файла по пути (--file [--root]) или JSON из stdin.

    RPA-38: обзор весит 200–260 КБ — вставлять YAML прямо в команду нельзя (~120 тыс. токенов вывода).
    """
    opts = {}
    it = iter(argv)
    for a in it:
        if a in ("--file", "--root"):
            opts[a] = next(it, None)
        else:
            raise ValueError(f"неизвестный аргумент {a!r}; допустимы --file, --root")
    doc = _load_doc(opts["--file"]) if "--file" in opts else json.load(sys.stdin)
    if opts.get("--root"):
        _priority_context_from_root(doc, opts["--root"])
        _monitoring_context_from_root(doc, opts["--root"])
    return doc


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "stamp-report":   # пишет файл отчёта; вход — аргументы, не stdin
        code, out = stamp_report(sys.argv[2:])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(code)
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(
            json.dumps({"error": f"unknown command; valid: {sorted(COMMANDS) + ['stamp-report']}",
                        "usage": "python3 assemble_artifact.py <command> --file artifact.yaml "
                                 "[--root <корень Claude-Memory>: контекст приоритета из решений и условий] "
                                 "| --anchor prior.yaml --current new.yaml [--review-type stock|bond] "
                                 "| < input.json"}),
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = _read_input(sys.argv[2:])
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON parse error: {exc}"}), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(COMMANDS[sys.argv[1]](data), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
