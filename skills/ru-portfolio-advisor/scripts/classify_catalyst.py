#!/usr/bin/env python3
"""
classify_catalyst.py

Эвристический классификатор catalyst kind (binary vs quantitative) для METH-1.
Принимает catalyst (id + trigger + опц. macro_dependency + опц. upside_pct), выдаёт
предложение `kind` + reasoning + confidence.

LLM (advisor) использует suggestion как anchor; финальное решение остаётся у LLM,
override должен быть с explicit basis.

CLI:
    python3 classify_catalyst.py --catalyst-json '{"id": "...", "trigger": "..."}'
    cat catalysts.json | python3 classify_catalyst.py --batch

Output (JSON):
    {
      "suggested_kind": "binary" | "quantitative",
      "confidence": "HIGH" | "MEDIUM" | "LOW",
      "reasoning": ["matched binary keyword 'record date'", ...],
      "alternatives_considered": ["quantitative"],
      "warnings": []
    }

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys


# ─────────────────────── keyword таблицы ───────────────────────

# Binary triggers — дискретные события с фиксированным исходом.
# Patterns case-insensitive; работают на русском и транслитерации.
BINARY_PATTERNS: list[tuple[str, str]] = [
    # Корпоративные события — отсечки, дивы, объявления
    (r"\botsech[ck]a|otsechki?\b", "дата отсечки реестра"),
    (r"\brecord\s+date\b", "record date (англ.)"),
    (r"\bdividend(?:naya)?\s+otsech", "дивидендная отсечка"),
    (r"\bspetsial[ьn]?nyy\s+dividend|special\s+dividend", "специальный дивиденд"),
    (r"\bdividend(naya)?\s+rekom|dividend(?:naya)?\s+vyplata", "дивидендная выплата"),

    # MSFO/IFRS квартальные отчёты — дискретный релиз
    (r"\bMSFO\s+Q[1-4]|IFRS\s+Q[1-4]\b", "квартальный отчёт MSFO/IFRS"),
    (r"\bgodovaya\s+otchotnost'?\b", "годовая отчётность"),

    # Сделки и M&A
    (r"\bM&A|sliyanie|pogloshchenie|merger|acquisition\b", "M&A"),
    (r"\bSPO|IPO\b", "размещение акций"),
    (r"\bbuyback|obratn[yiou]+\s+vykup\b", "обратный выкуп"),
    (r"\bsplit|split-?off|spin-?off\b", "split / spin-off"),

    # Регуляторные / лицензии
    (r"\bapproval|odobrenie|odobreno|razresh[еe]nie\b", "регуляторное одобрение"),
    (r"\blicenz|certifikat\b", "лицензия / сертификат"),
    (r"\bzakonoprokt|prinyatie\s+zakona|izmenenie\s+nalog\b", "законодательное изменение"),
    (r"\btarifn[oa][ея]\s+resh[еe]ni[ея]|tariff\s+decision\b", "тарифное решение"),

    # Геополитика — дискретные исходы
    (r"\bsnyati\w*\s+sanktsiy?|sanctions?\s+lift|lift(?:ing)?\s+sanctions?\b", "снятие санкций"),
    (r"\bvvedeni\w*\s+sanktsiy|imposition\s+of\s+sanctions\b", "введение санкций"),
    (r"\buregulirov\w+|resolution\b", "урегулирование"),
    (r"\bzapusk\w+|launch[ie]|vyvod\b.*\bna\s+rynok\b", "запуск / вывод продукта"),

    # Корпоративная завершённость
    (r"\bsvor\w+|сворач\w+|cessation|conclusion\b", "сворачивание / cessation"),
    (r"\bzaversheniy?e|completion|closing\b", "завершение"),
    (r"\bdefault|reorganization|restructur[ie]\b", "дефолт / реструктуризация"),
    (r"\bredemption|pogasheniy?e\b", "погашение"),
    (r"\bvozobnovleniy?e\s+(?:dividend|vyplat|prog)", "возобновление выплат / программы"),

    # Tail-risks с привязкой к event
    (r"\bcapex\b.{0,30}\b(?:overrun|prevysha\w*|exceed)", "перерасход capex (event)"),
]

# Quantitative triggers — непрерывные / постепенные величины.
# Patterns permissive к Russian declensions и transliteration variants.
QUANT_PATTERNS: list[tuple[str, str]] = [
    # Re-rating / multiples
    (r"\bre[\s-]?reyting|re[\s-]?rating|rerating|rost\s+mul[ьt]?tiplikator", "re-rating мультипликаторов"),
    (r"\bmultipl\w*\s+expansion|multipl\w*\s+ex[ps]ans", "expansion мультипликаторов"),

    # Темпы роста / разрастание (с любым "rost" + предметом)
    (r"\brost\s+vyru\w+", "рост выручки"),
    (r"\brost\s+(?:GMV|EBITDA|ChP|chistoy\s+pribyli|net\s+income|FCF)\b", "рост ключевой метрики"),
    (r"\brost\s+kredit\w*", "рост кредитования / кредитного портфеля"),
    (r"\brost\s+portfel\w*", "рост портфеля"),
    (r"\brost\s+ARR|rost\s+take\s+rate", "рост ARR / take rate"),
    (r"\brost\s+flot\w*", "рост флота"),
    (r"\brost\s+gos\w+", "рост госзакупок / госконтрактов"),
    (r"\brost\s+rynk\w+|rost\s+reklam\w+", "рост рынка / рекламы"),
    (r"\brost\s+klinik|otkry\w+\s+klinik", "сеть клиник — рост"),
    (r"\brevenue\s+growth|credit\s+growth\b", "growth keyword (en)"),
    (r"\bgrowth\s+accelerati(?:on|ya)\b", "ускорение роста"),
    (r"\brasshireniy?e|expansion\b", "расширение"),
    (r"\bmasshtab\w+|scaling|scale-up\b", "масштабирование"),
    (r"\borganicheski\w+\s+rost", "органический рост"),
    (r"\bperekhod\w+\s+na\s+EV|transition\s+to\s+EV", "переход на EV"),
    (r"\buskoreni\w+\s+perekhod", "ускорение перехода"),

    # Маржинальные изменения
    (r"\bszhati\w*\s+marzhi|margin\s+compression\b", "сжатие маржи"),
    (r"\bmarzha\s+rast[еe]t|margin\s+expansion\b", "рост маржи"),
    (r"\bszhati\w*\s+NIM|szhati\w+\s+NIM|NIM\s+szhati\w*|NIM\s+compression\b", "сжатие NIM"),
    (r"\buluchsh\w*\s+NIM|NIM\s+uluchsh\w*|NIM\s+improvement\b", "улучшение NIM"),

    # Macro reprice (rate cycle, FX, commodity)
    (r"\bsnizheni\w*\s+(?:KS|stavki|klyu[чc]\w*\s+stavki|rate)", "rate cycle — снижение КС"),
    (r"\bKS\s+\d", "уровень КС numeric (path)"),
    (r"\bperetok\s+kapital\w*|capital\s+inflow\b", "переток капитала"),
    (r"\bcost\s+of\s+funding|stoimost'?\s+fondirovani\w+\b", "стоимость фондирования"),
    (r"\bozhivleni\w*\s+(?:potreb|kredit|sprosa)", "оживление потребкредитования / спроса"),
    (r"\bnormal[ie]zatsi\w*\s+(?:DKP|KS|stavki)", "нормализация ДКП/КС"),
    (r"\bstavki\s+po\s+ipotek\w+", "ставки по ипотеке"),

    # Доля рынка
    (r"\bdol\w+\s+rynka|market\s+share\b", "доля рынка"),

    # Долгосрочный rolldown / fundament
    (r"\brost\s+klient\w+\s+bazy|customer\s+base\s+growth\b", "рост клиентской базы"),
    (r"\boperat\w+\s+ef?ek[tц]i[vw]nost'?\b", "операционная эффективность"),

    # Commodity prices / continuous quantities
    (r"\bBrent\s+L[123]|gold\s+price\s+L[123]\b|XAU/USD", "сырьевые L-прогнозы"),
    (r"\bsezonn\w*\s+pik|seasonal\s+peak\b", "сезонный пик"),

    # AI / монетизация — gradient
    (r"\bmonetiz\w*", "монетизация"),
    (r"\bimport\s+substitution|importozameshcheni\w*", "импортозамещение"),
]


# ─────────────────────── главный классификатор ───────────────────────

def classify_catalyst(catalyst: dict) -> dict:
    """
    Возвращает dict с полями:
      suggested_kind: 'binary' | 'quantitative'
      confidence: 'HIGH' | 'MEDIUM' | 'LOW'
      reasoning: list[str]
      alternatives_considered: list[str]
      warnings: list[str]
    """
    trigger = (catalyst.get("trigger") or "").lower()
    cat_id = (catalyst.get("id") or "").lower()
    text = f"{cat_id} {trigger}"

    binary_hits: list[str] = []
    quant_hits: list[str] = []

    for pattern, label in BINARY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            binary_hits.append(label)
    for pattern, label in QUANT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            quant_hits.append(label)

    # Decision
    suggested: str
    confidence: str
    reasoning: list[str] = []
    alternatives: list[str] = []
    warnings: list[str] = []

    if binary_hits and not quant_hits:
        suggested = "binary"
        confidence = "HIGH" if len(binary_hits) >= 2 else "MEDIUM"
        reasoning = [f"binary keyword: {h}" for h in binary_hits]
    elif quant_hits and not binary_hits:
        suggested = "quantitative"
        confidence = "HIGH" if len(quant_hits) >= 2 else "MEDIUM"
        reasoning = [f"quantitative keyword: {h}" for h in quant_hits]
    elif binary_hits and quant_hits:
        # Конфликт — берём с большим числом совпадений
        if len(quant_hits) > len(binary_hits):
            suggested = "quantitative"
            confidence = "MEDIUM"
            reasoning = [f"quantitative keyword: {h}" for h in quant_hits]
            alternatives.append("binary")
            warnings.append(
                f"conflicting keywords: binary hits={binary_hits}; quant hits={quant_hits}. "
                "Manual review recommended."
            )
        elif len(binary_hits) > len(quant_hits):
            suggested = "binary"
            confidence = "MEDIUM"
            reasoning = [f"binary keyword: {h}" for h in binary_hits]
            alternatives.append("quantitative")
            warnings.append(
                f"conflicting keywords: binary hits={binary_hits}; quant hits={quant_hits}. "
                "Manual review recommended."
            )
        else:
            suggested = "quantitative"  # tie-break: quant безопаснее (отражает scenario detail)
            confidence = "LOW"
            reasoning = [f"binary hit: {h}" for h in binary_hits] + \
                        [f"quant hit: {h}" for h in quant_hits]
            alternatives.append("binary")
            warnings.append("tie between binary and quantitative — LOW confidence; manual review required")
    else:
        # Ничего не подошло
        suggested = "binary"  # safer default: discrete unless proven continuous
        confidence = "LOW"
        reasoning.append("no keyword matched — defaulting to binary (safer assumption)")
        alternatives.append("quantitative")
        warnings.append("no keyword matched: classifier ungrounded, manual review required")

    return {
        "suggested_kind": suggested,
        "confidence": confidence,
        "reasoning": reasoning,
        "alternatives_considered": alternatives,
        "warnings": warnings,
    }


# ─────────────────────── batch ───────────────────────

def classify_batch(catalysts: list[dict]) -> list[dict]:
    """Возвращает list of {ticker, catalyst_id, suggestion}."""
    out = []
    for c in catalysts:
        sug = classify_catalyst(c)
        out.append({
            "ticker": c.get("ticker"),
            "catalyst_id": c.get("id"),
            "trigger": c.get("trigger"),
            "macro_dependency": c.get("macro_dependency"),
            "suggestion": sug,
        })
    return out


# ─────────────────────── CLI ───────────────────────

def _cli():
    ap = argparse.ArgumentParser(description="Classify catalyst kind (METH-1)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--catalyst-json", help="Single catalyst JSON string")
    g.add_argument("--batch", action="store_true", help="Read list of catalysts from stdin")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if args.catalyst_json:
        cat = json.loads(args.catalyst_json)
        result = classify_catalyst(cat)
    else:
        cats = json.load(sys.stdin)
        if not isinstance(cats, list):
            print("Error: --batch expects JSON array of catalysts on stdin", file=sys.stderr)
            sys.exit(2)
        result = classify_batch(cats)

    out_kwargs = {"ensure_ascii": False}
    if args.pretty:
        out_kwargs["indent"] = 2
    sys.stdout.write(json.dumps(result, **out_kwargs))
    sys.stdout.write("\n")


if __name__ == "__main__":
    _cli()
