"""rating_check.py — правило «рейтинг пора перепроверить» для обзора облигаций (weekly-bonds-review).

Одна функция для скриптов советника (prior_digest, render_weekly_md) и валидатора save-to-library.
Канон лежит в _shared-references/; в упакованном .skill — в scripts/ рядом (pack.sh по импорту). Только stdlib.

Правило: корпоративная бумага попадает в список, если credit_rating_checked_at пуст/нечитаем ИЛИ
старше RATING_CHECK_MAX_AGE_DAYS дней относительно опорной даты. Долг РФ исключён при любой дате:
ОФЗ (bond_type == "ofz") и выпуски Минфина РФ другого типа (замещающие еврооблигации — по эмитенту).
Иностранный суверен остаётся в правиле: его рейтинг меняется. Корпоративная бумага без рейтинга
(credit_rating пуст) тоже подлежит проверке — по той же дате.
"""
from __future__ import annotations

from datetime import date

RATING_CHECK_MAX_AGE_DAYS = 28
SOVEREIGN_BOND_TYPES = frozenset({"ofz"})


def parse_check_date(value) -> date | None:
    """YYYY-MM-DD (строка или date) -> date; всё остальное -> None."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


RF_SOVEREIGN_ISSUER_MARKS = ("министерство финансов российской федерации", "минфин рф", "минфин россии")


def is_sovereign(entry: dict) -> bool:
    """Долг РФ: ОФЗ по типу или выпуск Минфина РФ по эмитенту (замещающие еврооблигации)."""
    if entry.get("bond_type") in SOVEREIGN_BOND_TYPES:
        return True
    issuer = str(entry.get("issuer") or "").lower()
    return any(m in issuer for m in RF_SOVEREIGN_ISSUER_MARKS)


def rating_check_due(entry: dict, as_of: date) -> bool:
    """True, если рейтинг этой бумаги пора перепроверить относительно as_of."""
    if not isinstance(entry, dict) or is_sovereign(entry):
        return False
    checked = parse_check_date(entry.get("credit_rating_checked_at"))
    if checked is None:
        return True
    return (as_of - checked).days > RATING_CHECK_MAX_AGE_DAYS


def bonds_due_for_rating_check(per_bond: dict, as_of: date) -> list[dict]:
    """[{key, name, issuer, credit_rating, credit_rating_agency, checked_at}] в порядке обзора."""
    out = []
    for key, e in (per_bond or {}).items():
        if rating_check_due(e, as_of):
            out.append({"key": key, "name": e.get("name"), "issuer": e.get("issuer"),
                        "credit_rating": e.get("credit_rating"),
                        "credit_rating_agency": e.get("credit_rating_agency"),
                        "checked_at": e.get("credit_rating_checked_at")})
    return out


def due_label(item: dict) -> str:
    """Короткая подпись для сводки: «Эмитент (ТИКЕР)»."""
    who = item.get("issuer") or item.get("name") or item["key"]
    return f"{who} ({item['key']})"
