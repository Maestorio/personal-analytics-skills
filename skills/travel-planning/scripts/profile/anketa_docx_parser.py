"""Парсер заполненного DOCX-анкеты → answers dict.

Идёт по параграфам DOCX, ищет якоря:
  - «Вопрос: …»          — старт нового вопроса (текст после двоеточия
                           матчится с QUESTIONS_BY_ID.text — fuzzy)
  - «Ответ: …»            — свободный ответ (для type=text)
  - «[x] значение (уточнение)» — выбранный вариант (для type=single/multi)
  - «[ ] значение»        — невыбранный вариант (игнорируется)

Сопоставление вопроса делается по тексту самого вопроса — это устойчиво
к перестановке секций и удалению нумерации пользователем в Word.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from docx import Document
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "python-docx не установлен. Поставь: "
        "`pip install python-docx --break-system-packages`"
    ) from e

from .anketa_spec import ANKETA_SECTIONS, ARCHETYPE_LEGACY_ALIASES, Question


@dataclass
class ParsedAnketa:
    answers: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)  # строки про edge cases


# ---------------------------------------------------------------------------
# Утилиты сопоставления вопросов
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Снять знаки препинания, привести к нижнему регистру, схлопнуть пробелы."""
    s = s.lower()
    s = re.sub(r"[«»\"'\(\)\[\]\.,;:!\?—\-–]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_question_index() -> list[tuple[str, Question]]:
    """Список (normalized_text, Question) для нахождения по prefix."""
    idx = []
    for sec in ANKETA_SECTIONS:
        for q in sec.questions():
            idx.append((_normalize(q.text), q))
    return idx


def _find_question_by_text(text: str, idx: list) -> Optional[Question]:
    """Найти Question, чей text лучше всего совпадает с переданным."""
    norm = _normalize(text)
    if not norm:
        return None
    # Точное совпадение
    for nt, q in idx:
        if nt == norm:
            return q
    # Префикс: question text — префикс introduced или наоборот
    for nt, q in idx:
        if nt.startswith(norm[:50]) or norm.startswith(nt[:50]):
            return q
    # Большой overlap (jaccard на словах)
    norm_words = set(norm.split())
    if not norm_words:
        return None
    best: Optional[Question] = None
    best_score = 0.0
    for nt, q in idx:
        qw = set(nt.split())
        if not qw:
            continue
        intersect = len(norm_words & qw)
        union = len(norm_words | qw)
        score = intersect / union
        if score > best_score and score >= 0.5:
            best_score = score
            best = q
    return best


# ---------------------------------------------------------------------------
# Извлечение строк ответа / чекбоксов
# ---------------------------------------------------------------------------

# Маркер «отмечено» — терпим к тому, что люди реально ставят: x/X, кир. х/Х,
# ✓, и «галочку» V/v / кир. В/в (V визуально ≈ ✓). Внутри скобок допускаем
# несколько символов и пробелы — `[v ]`, `[x ]`, `[ v ]` читаются как «отмечено».
_CHECK_MARK_CHARS = "xXхХvVвВ✓"
_CHECKBOX_RE = re.compile(rf"^\s*\[([{_CHECK_MARK_CHARS}\s]*)\]\s+(.+?)\s*$")
_QUESTION_RE = re.compile(r"^\s*Вопрос:\s*(.+?)\s*$", re.IGNORECASE)
_ANSWER_RE = re.compile(r"^\s*Ответ:\s*(.*?)\s*$", re.IGNORECASE)


def _parse_option_line(text: str) -> Optional[tuple[bool, str, str]]:
    """Распарсить строку чекбокса.

    Возвращает (selected, value, clarification) или None если не чекбокс.
    """
    m = _CHECKBOX_RE.match(text)
    if not m:
        return None
    mark = m.group(1)
    selected = bool(re.search(rf"[{_CHECK_MARK_CHARS}]", mark))
    rest = m.group(2).strip()
    # Уточнение в круглых скобках после варианта
    clar = ""
    m_clar = re.match(r"^(.+?)\s*\(\s*(.+?)\s*\)\s*$", rest)
    if m_clar:
        value = m_clar.group(1).strip()
        clar = m_clar.group(2).strip()
    else:
        value = rest
    return selected, value, clar


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


def parse_docx(in_path: str | Path) -> ParsedAnketa:
    """Распарсить заполненный DOCX → answers dict."""
    in_path = Path(in_path).expanduser()
    doc = Document(str(in_path))
    qidx = _build_question_index()

    result = ParsedAnketa()

    current_q: Optional[Question] = None
    current_selected: list = []
    current_clarifications: dict = {}
    current_answer_text: str = ""
    has_text_answer = False  # видели ли мы строку «Ответ:» для current_q

    def flush() -> None:
        """Закоммитить накопленные данные текущего вопроса в answers."""
        nonlocal current_q, current_selected, current_clarifications
        nonlocal current_answer_text, has_text_answer
        if current_q is None:
            return
        if current_q.type == "text":
            if has_text_answer and current_answer_text:
                result.answers[current_q.id] = {"text": current_answer_text}
        else:
            if current_selected:
                # multi: оставим все; single: возьмём только первый при коллизии
                sel = current_selected
                if current_q.type == "single" and len(sel) > 1:
                    result.warnings.append(
                        f"вопрос «{current_q.text[:60]}»: выбрано {len(sel)} опций при "
                        f"типе single — взята первая ({sel[0]})"
                    )
                    sel = sel[:1]
                clar = {k: v for k, v in current_clarifications.items() if k in sel}
                result.answers[current_q.id] = {"selected": sel, "clarifications": clar}
        current_q = None
        current_selected = []
        current_clarifications = {}
        current_answer_text = ""
        has_text_answer = False

    for para in doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue

        # Новый вопрос?
        m_q = _QUESTION_RE.match(txt)
        if m_q:
            flush()
            q_text = m_q.group(1).strip()
            current_q = _find_question_by_text(q_text, qidx)
            if current_q is None:
                result.warnings.append(
                    f"не удалось сопоставить вопрос с текстом «{q_text[:80]}»"
                )
            continue

        if current_q is None:
            continue

        # Ответ (свободный текст)
        m_a = _ANSWER_RE.match(txt)
        if m_a:
            has_text_answer = True
            ans = m_a.group(1).strip()
            if ans:
                current_answer_text = ans
            continue

        # Чекбокс?
        opt = _parse_option_line(txt)
        if opt is None:
            # Любой не-структурный параграф между «Ответ: …» и следующим вопросом
            # игнорируем (это могут быть «Пояснения:» / «Выбери один»).
            continue
        selected, value, clar = opt
        # value может содержать опечатки/регистр + дописку после варианта
        matched = _match_option_value(current_q, value)
        if matched is None:
            result.warnings.append(
                f"вопрос «{current_q.text[:50]}»: значение «{value}» не из набора опций"
            )
            continue
        canonical, extra_clar = matched
        # уточнение: в скобках (clar) + хвост после варианта без скобок (extra_clar)
        full_clar = " ".join(p for p in (clar, extra_clar) if p).strip()
        if selected:
            if canonical not in current_selected:
                current_selected.append(canonical)
            if full_clar:
                current_clarifications[canonical] = full_clar

    flush()
    return result


def _match_option_value(q: Question, raw_value: str) -> Optional[tuple[str, str]]:
    """Сопоставить введённое значение опции с каноническим именем из spec.

    Возвращает `(canon, extra_clar)` или None. `extra_clar` — хвост, который
    пользователь дописал ПОСЛЕ канон-варианта без круглых скобок (напр.
    «нет жёсткого мнения 2-3 ночи» → canon «нет жёсткого мнения», extra
    «2-3 ночи»); иначе пустая строка. Без этого дописка молча терялась.
    """
    norm = _normalize(raw_value)
    if not norm:
        return None
    # Legacy-имя архетипа (анкета старой выгрузки) → каноническая опция.
    if q.id == "архетип.значение":
        for legacy, canon in ARCHETYPE_LEGACY_ALIASES.items():
            ln = _normalize(legacy)
            if norm == ln or norm.startswith(ln + " "):
                extra = " ".join(raw_value.split()[len(legacy.split()):]).strip(" .,;—–-")
                return canon, extra
    # Точное совпадение.
    for canon, _desc in q.options:
        if _normalize(canon) == norm:
            return canon, ""
    # Префиксное совпадение.
    for canon, _desc in q.options:
        cn = _normalize(canon)
        if cn and norm.startswith(cn):
            # пользователь дописал хвост после варианта — сохранить как уточнение
            # (из оригинала, с регистром/цифрами): слова после канона
            extra = " ".join(raw_value.split()[len(canon.split()):]).strip(" .,;—–-")
            return canon, extra
        if norm and cn.startswith(norm):
            # пользователь ввёл меньше канона — дописки нет
            return canon, ""
    return None
