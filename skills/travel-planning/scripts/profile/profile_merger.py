"""Объединение нескольких answers-словарей в один merged.

Реализует правила §4.1 profile-management.md:
  - MIN              — взять более ограничительную версию (для choice с ranking)
  - UNION_TEXT       — склеить текстовые ответы через `; `
  - UNION_MULTI      — объединение selected опций (multi-choice)
  - INTERSECT_MULTI  — пересечение selected (только то, на что согласны все)
  - ASK              — расхождение требует уточнения от пользователя

Возвращает (merged_answers, ask_items) где ask_items описывает поля,
которые требуют ручного резолюшна.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from .anketa_spec import ANKETA_SECTIONS, QUESTIONS_BY_ID


# ---------------------------------------------------------------------------
# Per-qid ordering (для MIN) и стратегии
# ---------------------------------------------------------------------------

# Порядок «менее ограничительное → более ограничительное» (MIN = первое
# валидное по слабейшему профилю).
ORDERINGS: dict[str, list] = {
    # темп — медленный самый «ограничительный» (требует расслабленного маршрута)
    "темп.значение":        ["активный", "умеренный", "медленный"],
    "форма.уровень":        ["хорошая", "средняя", "ограниченная"],
    # класс размещения — премиум «выше», бюджетный «ниже». MIN = более низкий
    # класс (исходим из «что устроит обоих» = более простое).
    # Edge: если кто-то выбрал «разное по поездке» — это ASK.
    "стиль.класс":          ["премиум", "средний", "бюджетный"],
    # ночные переезды — MIN = более строгий («исключено» строже «нежелательно»
    # строже «ок»).
    "стиль.ночные":         ["ок", "нежелательно", "исключено"],
    # планирование — MIN = более организованное (компромисс «обоих устроит»)
    "стиль.планирование":   ["независимое", "гибрид", "организованное"],
    # частота смены локаций — MIN = более медленный темп (5+ ночей строже 1-2)
    "частота.значение":     ["1–2 ночи", "3–5 ночей", "5+ ночей", "нет жёсткого мнения"],
    # фото-уровень — MIN = более слабый интерес (не делает > телефон > для себя > проф.)
    "фото.уровень":         ["профессионально", "для себя", "на телефон", "не делает"],
    # локальные платежи — MIN = менее «готов»
    "платежи.локальные":    ["да", "при необходимости", "нет"],
}


# Стратегии для каждого qid (per §4.1).
QID_STRATEGY: dict[str, str] = {
    # MIN — выбор более ограничительного по rank
    "темп.значение":            "MIN",
    "форма.уровень":            "MIN",
    "стиль.класс":              "MIN_OR_ASK",   # "разное" → ASK
    "стиль.ночные":             "MIN",
    "стиль.планирование":       "MIN",
    "частота.значение":         "ASK",          # «1-2 vs 3-5» — это противоположные предпочтения
    "платежи.локальные":        "MIN",

    # UNION — объединить значения, сохранив все
    "опыт.значение":            "UNION_TEXT",
    "состав.языки":             "UNION_TEXT",
    "интересы.значение":        "UNION_TEXT",
    "платежи.карты":            "UNION_MULTI",
    "форма.треки":              "UNION_TEXT",
    "форма.ограничения":        "UNION_TEXT",
    "гастро.напитки":           "UNION_TEXT",

    # Переносимость — порог принадлежит человеку, не группе: UNION
    # с атрибуцией, планирование идёт по самому низкому порогу
    # (см. profile-management.md §4.1, «Особый случай — Переносимость»).
    "переносимость.климат":     "UNION_TEXT",
    "переносимость.экспозиция": "UNION_TEXT",
    "переносимость.транспорт":  "UNION_TEXT",

    # STRICTER (через UNION_TEXT для исключений / гастро.ограничений —
    # каждое исключение одного автоматически попадает в общий список)
    "исключения.значение":      "UNION_TEXT",
    "исключения.мягкие":        "UNION_TEXT",
    "гастро.ограничения":       "UNION_TEXT",
    # Транспорт — пересечение (то, что устраивает всех)
    "стиль.транспорт":          "INTERSECT_MULTI",
    "гастро.стиль":             "INTERSECT_MULTI",

    # ASK — расхождение требует решения пользователя
    "бюджет.ориентир":          "ASK",
    "бюджет.включает":          "ASK",
    "бюджет.переплата":         "ASK",
    "состав.люди_паспорта":     "ASK",
    "возраст.значение":         "ASK",
    "вождение.готовность":      "ASK",
    "вождение.гео_ограничения": "ASK",
    "архетип.значение":         "ASK",
    "базовый_город.значение":   "ASK",
    "фото.уровень":             "ASK",
    "фото.жанры":               "UNION_TEXT",
    "дополнительно.значение":   "UNION_TEXT",
}


@dataclass
class AskItem:
    qid: str
    question_text: str
    section_title: str
    reason: str
    sources: list = field(default_factory=list)  # [(profile_id, value_str)]


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def _value_signature(qid: str, ans: Optional[dict]) -> str:
    """Канонизированная сигнатура ответа для сравнения."""
    if not ans:
        return ""
    q = QUESTIONS_BY_ID.get(qid)
    if q and q.type == "text":
        return (ans.get("text") or "").strip().lower()
    sel = ans.get("selected") or []
    return "|".join(sorted(sel))


def _format_value(qid: str, ans: dict) -> str:
    q = QUESTIONS_BY_ID.get(qid)
    if q and q.type == "text":
        return (ans.get("text") or "").strip()
    sel = ans.get("selected") or []
    return ", ".join(sel)


def _section_for(qid: str) -> str:
    for sec in ANKETA_SECTIONS:
        for q in sec.questions():
            if q.id == qid:
                return sec.title
    return ""


def _question_text(qid: str) -> str:
    q = QUESTIONS_BY_ID.get(qid)
    return q.text if q else qid


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


def merge_answers(
    profile_answers_list: list[dict],
    profile_ids: list[str],
) -> tuple[dict, list[AskItem]]:
    """Объединить answers нескольких профилей.

    Возвращает (merged_answers, ask_items).
    """
    if len(profile_answers_list) != len(profile_ids):
        raise ValueError("profile_answers_list и profile_ids разной длины")
    if len(profile_answers_list) < 2:
        raise ValueError("MERGE требует ≥2 профилей")

    merged: dict = {}
    ask_items: list[AskItem] = []

    all_qids: set = set()
    for a in profile_answers_list:
        all_qids.update(a.keys())

    n_profiles = len(profile_ids)

    for qid in sorted(all_qids):
        sources = [
            (pid, a[qid]) for pid, a in zip(profile_ids, profile_answers_list)
            if qid in a and a[qid]
        ]
        if not sources:
            continue

        strategy = QID_STRATEGY.get(qid, "ASK")
        q = QUESTIONS_BY_ID.get(qid)
        if q is None:
            continue

        sigs = [_value_signature(qid, val) for _pid, val in sources]
        all_agree = (len(sources) == n_profiles and len(set(sigs)) == 1)

        # Для **не-ASK** стратегий: один источник или полное согласие → берём как есть.
        if strategy != "ASK" and (len(sources) == 1 or all_agree):
            merged[qid] = sources[0][1]
            continue

        # Для **ASK**: даже single-source требует явного подтверждения при MERGE
        # (§4.1 «архетип — обязательно при MERGE», «состав — подтвердить» и т.д.).
        # Исключение — все источники согласны и заполнены: тогда без вопроса.
        if strategy == "ASK" and all_agree:
            merged[qid] = sources[0][1]
            continue

        # Расхождение — применяем стратегию.
        if strategy in ("MIN", "MIN_OR_ASK"):
            ordering = ORDERINGS.get(qid, [])
            if not ordering:
                # MIN без ordering — fallback к ASK
                ask_items.append(_ask_for(qid, sources, "MIN без ordering"))
                continue
            valid = [(pid, val) for pid, val in sources
                     if val.get("selected") and val["selected"][0] in ordering]
            if not valid:
                ask_items.append(_ask_for(qid, sources, "ни одно значение не в ordering"))
                continue
            # Для MIN_OR_ASK — если кто-то выбрал «разное по поездке» / «нет
            # жёсткого мнения», это означает «гибкость» → ASK.
            flexible_markers = {"разное по поездке", "нет жёсткого мнения"}
            if strategy == "MIN_OR_ASK" and any(
                val["selected"][0] in flexible_markers for _pid, val in valid
            ):
                ask_items.append(_ask_for(qid, sources, "часть профилей выбрала гибкий вариант"))
                continue
            best = max(valid, key=lambda x: ordering.index(x[1]["selected"][0]))
            merged[qid] = {
                "selected": [best[1]["selected"][0]],
                "clarifications": dict(best[1].get("clarifications") or {}),
            }
        elif strategy == "UNION_TEXT":
            parts = []
            for pid, val in sources:
                t = (val.get("text") or "").strip()
                if t:
                    parts.append(f"{pid}: {t}")
            if parts:
                merged[qid] = {"text": "; ".join(parts)}
        elif strategy == "UNION_MULTI":
            all_sel: list = []
            clar: dict = {}
            for _pid, val in sources:
                for s in (val.get("selected") or []):
                    if s not in all_sel:
                        all_sel.append(s)
                for k, v in (val.get("clarifications") or {}).items():
                    if v and k not in clar:
                        clar[k] = v
            if all_sel:
                merged[qid] = {"selected": all_sel, "clarifications": clar}
        elif strategy == "INTERSECT_MULTI":
            sets = [set(val.get("selected") or []) for _pid, val in sources]
            sets = [s for s in sets if s]
            if not sets:
                continue
            intersection = set.intersection(*sets)
            if intersection:
                # Сохраняем порядок из первого профиля
                first_sel = sources[0][1].get("selected") or []
                ordered = [x for x in first_sel if x in intersection]
                merged[qid] = {"selected": ordered, "clarifications": {}}
            else:
                ask_items.append(_ask_for(qid, sources, "пересечение пусто"))
        elif strategy == "ASK":
            reason = (
                "значения расходятся" if len(sources) > 1
                else "поле обязательно к подтверждению при MERGE (§4.1)"
            )
            ask_items.append(_ask_for_with_missing(qid, sources, profile_ids, reason))

    return merged, ask_items


def _ask_for(qid: str, sources: list, reason: str) -> AskItem:
    return AskItem(
        qid=qid,
        question_text=_question_text(qid),
        section_title=_section_for(qid),
        reason=reason,
        sources=[(pid, _format_value(qid, val)) for pid, val in sources],
    )


def _ask_for_with_missing(qid: str, sources: list, all_pids: list, reason: str) -> AskItem:
    """ASK item с явным указанием профилей, где поле не заполнено."""
    present_pids = {pid for pid, _ in sources}
    items: list = []
    for pid in all_pids:
        if pid in present_pids:
            val = next(v for p, v in sources if p == pid)
            items.append((pid, _format_value(qid, val)))
        else:
            items.append((pid, "(не указано)"))
    return AskItem(
        qid=qid,
        question_text=_question_text(qid),
        section_title=_section_for(qid),
        reason=reason,
        sources=items,
    )


# ---------------------------------------------------------------------------
# Резолв profile_id для merged
# ---------------------------------------------------------------------------

OWNER_CANDIDATES = ("алексей",)  # см. §4 — владелец всегда первым


def merged_profile_id(profile_ids: list[str]) -> str:
    """Из правил §4: владелец первым, остальные по алфавиту.

    Если ни один из profile_ids не «владелец» — все по алфавиту.
    """
    owners = [p for p in profile_ids if p in OWNER_CANDIDATES]
    others = sorted([p for p in profile_ids if p not in OWNER_CANDIDATES])
    if owners:
        return "_".join(owners + others)
    return "_".join(others)
