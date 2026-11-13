#!/usr/bin/env python3
r"""
compute_per_position.py — детерминистический numeric crunching для блока per_position
итогового stress-test YAML (schema v2: блок by_horizon на позицию, V2-A).

Запуск:
  python3 compute_per_position.py \
    --snapshot /path/to/portfolio-{date}.json \
    --scenarios /path/to/scenarios-fragment.yaml \   # v2: factors_by_horizon на сценарий
    --priors /path/to/betas-priors.json \
    --output /path/to/per_position-fragment.yaml \
    [--regression-mode priors|moex]   # default: priors
    [--horizons 12,20,36]             # v1-вход-обёртка; v2 берёт горизонты из данных
    [--horizon-coverage cov.json]     # ci_inflation на горизонт (из compute_horizon_factors)
    [--political-scale-check error|warn|off]   # default: error (P0-1)

Контракт единиц бет (P0-1, единый для всех факторов): β — процентные пункты цены
на ОДНУ единицу фактора в его собственной единице (% для brent/FX/xauusd, п.п. для
cbr_rate, интенсивность 1.0 по шкале [-1..+1] для sanctions/geopol). Политическая
бета банков ≈ -35, НЕ -0.35: долевая запись отличается ×100 и молча зануляет канал.
Гард --political-scale-check ловит обе стороны ошибки.

P1-3: опциональное поле priors `sanctions_position ∈ [0,1]` — где бумага стоит на
санкционной шкале сегодня (0 — не тронута, 1 — максимально заблокирована). Задано →
движение фактора `sanctions` клампится доступным ходом: у уже заблокированной
бумаги мало места ужесточать, но всё место — снимать. Не задано → полная
интенсивность (прежнее поведение). `geopol` не клампится никогда.

Беты SS-1 — месячные, горизонт-независимые (D4-2): считаются один раз, общие на все
горизонты. От горизонта зависят только factors_by_horizon и CI-инфляция при
экстраполяции года FCA. v1-вход (плоский factors) принимается → обёртка by_horizon.{h20}.

Архитектура:
  priors — ручные беты из betas-priors.json (factor_betas_r2 = null, CI placeholder).
  moex   — эмпирические беты через OLS (numpy.linalg.lstsq) на 24 мес MOEX/CBR
           истории: brent (FORTS-стичинг), usdrub/cnyrub (selt), cbr_rate (Δ п.п.,
           CBR SOAP). factor_betas_r2 заполняется; macro_blindspot авто при R²<0.3.
           sanctions/geopol остаются на priors (D-C). Best-effort: сбой сети/нехватка
           истории по тикеру → graceful fallback на priors + warning, run не падает.

Выход — YAML-фрагмент с блоком per_position:, готовый к копированию в финальный stress-YAML.
"""

from __future__ import annotations

import argparse
import calendar
import gzip
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

# PSS-7: контракт входа и его гарды вынесены в соседний модуль. sys.path страхует
# запуск скриптом из чужого каталога — внутри скилла это первый sibling-импорт,
# и молчаливый ImportError в Claude.ai стоил бы прогона.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import (  # noqa: E402  (после правки sys.path — намеренно)
    CANONICAL_FACTORS,
    EQUITY_TOKENS,
    MONEY_MARKET_TICKERS,
    NON_EQUITY_TOKENS,
    POLITICAL_BETA_MAX_BOND,
    POLITICAL_BETA_MAX_PLAUSIBLE,
    POLITICAL_BETA_MIN_PLAUSIBLE,
    POLITICAL_FACTORS,
    POSITION_REQUIRED_BETA,
    _asset_type_of,
    _fmt_list,
    _is_equity_like,
    _portfolio_tickers,
    check_betas_numeric,
    check_political_beta_scale,
    check_political_horizon_path,
    check_priors_structure,
    check_sanctions_positions,
    check_scenario_weights,
    is_excluded,
    is_money_market,
)
from input_contract import (  # noqa: E402  — P2-4, отдельным блоком для читаемости
    CI_LEGACY_DELTA_SHARE,
    CI_MIN_HALF_WIDTH_PP,
    FACTOR_BETA_UNCERTAINTY,
    FACTOR_BETA_UNCERTAINTY_DEFAULT,
)


# ── SS-1: эмпирические факторные беты через OLS на MOEX истории ──
ISS_BASE = "https://iss.moex.com/iss"
CBR_SOAP_ENDPOINT = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
HTTP_USER_AGENT = "portfolio-scenario-stress/1.0 (+claude.ai skill)"
HTTP_TIMEOUT = 20
REGRESSION_MONTHS = 24          # окно истории по умолчанию
MIN_REGRESSION_OBS = 12         # минимум выровненных мес. наблюдений для OLS
# Гард качества данных. Неадаптированные сплиты/реорганизации дают выброс месячной
# доходности (напр. реверс-сплит VTB 2024 → +462624% за месяц). Такое наблюдение
# исключается из регрессии; если бета всё равно абсурдна (почти сингулярная матрица,
# короткая история) — откат на ручные priors конкретного тикера.
OUTLIER_RETURN_PCT = 100.0      # |мес. доходность| выше → исключить наблюдение
MAX_ABS_BETA = 15.0             # |β| выше → регрессия вырождена, откат на priors
# Непрерывные рыночные факторы — регрессоры OLS, в единицах контракта §5.6
# (events-yaml-spec.md): brent/usdrub/cnyrub — % мес.; cbr_rate — Δ п.п.
# sanctions/geopol НЕ регрессируются (D-C): событие 0/1 ≠ индекс эскалации [-1..+1] —
# остаются на ручных priors.
REGRESSION_FACTORS = ["brent", "usdrub", "cnyrub", "cbr_rate"]
# SECID валютных пар на MOEX selt (CETS). ВНИМАНИЕ: биржевые торги USD/RUB
# (USD000UTSTOM) на MOEX приостановлены с июня 2024 (санкции на Мосбиржу) —
# CLOSE приходит нулевым. Поэтому FX по умолчанию берём из официальных курсов
# ЦБ (CBR_CURRENCY_CODES). MOEX-валюта оставлена для инструментов, что ещё торгуются.
CURRENCY_SECID = {"usdrub": "USD000UTSTOM", "cnyrub": "CNYRUB_TOM"}
# Коды валют ЦБ для XML_dynamic (официальный курс): USD, CNY.
CBR_CURRENCY_CODES = {"usdrub": "R01235", "cnyrub": "R01375"}
CBR_DYNAMIC_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"
# Коды месяцев фьючерсов FORTS (Jan..Dec).
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


# Hard-coded idiosyncratic list — позиции, для которых макро объясняет <30% дисперсии.
# Расширенное обоснование — в references/idiosyncratic-tickers.md.
# В Phase 4.2 этот список станет необязательным (automatic detection через r2 < 0.3).
IDIOSYNCRATIC_TICKERS = {
    "MDMG": "Healthcare M&A pipeline — открытие новых клиник, valuation pipeline-driven",
    "PRMD": "Pharma — FDA/Минздрав approval, IP events, не циклы",
    "OZON": "Operational milestone — выход в EBITDA-positive, не financial",
    "WUSH": "Regulatory event-driven — самокаты, регуляторика городов",
    "DOMRF": "Политическое решение — реформа льготной ипотеки, не макро",
}


def load_yaml_minimal(path: Path) -> dict[str, Any]:
    """
    Минимальный YAML-парсер для structured-input. Используем PyYAML если доступен,
    иначе падаем с понятной ошибкой.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write(
            "ERROR: модуль 'yaml' не установлен. Установить: "
            "`pip install pyyaml --break-system-packages`\n"
        )
        sys.exit(2)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(obj: Any) -> str:
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: pyyaml не установлен.\n")
        sys.exit(2)
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)


def compute_total_value(holdings: list[dict[str, Any]]) -> float:
    return sum((h.get("value_rub") or 0) for h in holdings if not h.get("is_blocked", False))


def merge_holding_legs(
    holdings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """
    Схлопывает ноги одной бумаги, разложенной по счетам (main + iis_3), в одну
    запись: `value_rub` суммой, `on_iis` — «хотя бы одна нога на ИИС-3»
    (контракт references/output-template.md и synthesizer-workflow.md IV).

    Зачем. `per_position` — словарь по тикеру, и без этого шага
    `per_position[ticker] = entry` затирал первую ногу второй: в артефакт уходил
    вес ОДНОГО счёта. Молча — гард покрытия считал по членству тикера, так что
    обе ноги числились покрытыми и покрытие показывало 100%. Реальный случай
    2026-08-04: ОФЗ 26238 (80 шт main + 130 шт ИИС-3) опубликована весом
    0.5358% вместо 0.8656%; загрузчик расщепление пометил
    (`iis_split_position`), потребитель — нет.

    Омонимы (разные бумаги под одним тикером) НЕ схлопываются: одним ключом
    `per_position` их не представить. Меньшая по стоимости уходит в
    `unmapped_tickers` — потеря становится видимой, а не тихой.

    Возвращает (merged, warnings, dropped). Порядок исходного списка сохранён:
    объединённая запись встаёт на место ПЕРВОЙ ноги. Исключённые (blocked,
    нулевые, рублёвый кэш) отсеиваются здесь же — основной цикл проверяет
    повторно и от этого не зависит.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for holding in holdings:
        excluded, _ = is_excluded(holding)
        if excluded:
            continue
        ticker = (holding.get("ticker") or "").upper()
        if ticker:
            groups.setdefault(ticker, []).append(holding)

    def _value(h: dict[str, Any]) -> float:
        return float(h.get("value_rub") or 0)

    merged: list[dict[str, Any]] = []
    warnings: list[str] = []
    dropped: list[dict[str, Any]] = []
    emitted: set[str] = set()

    for holding in holdings:
        excluded, _ = is_excluded(holding)
        if excluded:
            continue
        ticker = (holding.get("ticker") or "").upper()
        if not ticker:
            # Без тикера — основной цикл сам отправит запись в unmapped_tickers.
            merged.append(holding)
            continue
        if ticker in emitted:
            continue
        emitted.add(ticker)

        legs = groups[ticker]
        if len(legs) == 1:
            merged.append(legs[0])
            continue

        isins = {(leg.get("isin") or "").upper() for leg in legs if leg.get("isin")}
        if len(isins) > 1:
            ranked = sorted(legs, key=_value, reverse=True)
            keep = ranked[0]
            for lost in ranked[1:]:
                dropped.append({
                    "ticker": ticker,
                    "weight_pct": None,
                    "reason": (
                        f"ticker collision: под тикером {ticker} несколько разных бумаг "
                        f"({', '.join(sorted(isins))}); в расчёт взята крупнейшая "
                        f"({(keep.get('isin') or '?').upper()}), эта "
                        f"({(lost.get('isin') or '?').upper()}, {_value(lost):,.0f} ₽) — нет"
                    ),
                })
            warnings.append(
                f"{ticker}: под одним тикером разные бумаги ({', '.join(sorted(isins))}) — "
                f"схлопывать нельзя. В расчёт взята крупнейшая, остальные в unmapped_tickers."
            )
            merged.append(keep)
            continue

        base = dict(max(legs, key=_value))
        total = sum(_value(leg) for leg in legs)
        base["value_rub"] = total
        base["on_iis"] = any(
            bool(leg.get("on_iis")) or leg.get("account") == "iis_3" for leg in legs
        )
        qtys = [leg.get("qty") for leg in legs]
        if all(isinstance(q, (int, float)) and not isinstance(q, bool) for q in qtys):
            base["qty"] = sum(qtys)
        # Счёт больше не один — оставленное поле было бы ложью про объединённую запись.
        base.pop("account", None)
        merged.append(base)

        parts = ", ".join(
            f"{leg.get('account') or '?'} {_value(leg):,.0f} ₽" for leg in legs
        )
        warnings.append(
            f"{ticker}: позиция разложена по счетам ({parts}) — ноги схлопнуты в одну "
            f"запись, вес считается от полной стоимости {total:,.0f} ₽."
        )

    return merged, warnings, dropped


def betas_for_money_market() -> dict[str, float]:
    return {f: 0.0 for f in CANONICAL_FACTORS}


def effective_sanctions_move(intensity: float, position: float) -> float:
    """
    P1-3: доступный ход по санкционной шкале с ТЕКУЩЕЙ позиции бумаги.

        effective = clamp(position + intensity, 0, 1) − position

    `position ∈ [0,1]` — где бумага стоит сегодня: 0 — санкциями не тронута,
    1 — максимально заблокирована. Асимметрия «ужесточение слабее, снятие сильнее»
    возникает ИЗ ПОЗИЦИИ, а не из двух разных бет: у бумаги на краю шкалы почти
    нет хода дальше, но есть весь ход обратно; у нетронутой — наоборот, санкционного
    дисконта в цене нет и снимать нечего.

    Замер 2026-08-03 (tools/research/pss-4-sanctions/): назначение SDN перевело
    Rusal с позиции 0 на ~0.9 и стоило −33.7% ⇒ β ≈ −37; последующий релиф дал
    +19.9% ⇒ откат позиции на 0.53, остаточная позиция 0.37 (Дерипаска остался
    в SDN, доля размыта принудительно) — форма воспроизводит обе стороны эпизода
    одним β. Один эпизод, две бумаги: форма не подогнана, но и не доказана.
    """
    pos = min(max(float(position), 0.0), 1.0)
    return min(max(pos + float(intensity), 0.0), 1.0) - pos


def compute_delta_pct(
    betas: dict[str, float],
    factors: dict[str, float],
    sanctions_position: float | None = None,
    *,
    with_contributions: bool = False,
):
    """
    Линейная свёртка β × factor по каноническому имени.
    factor_value читается напрямую из scenarios.<id>.factors. Отсутствующие факторы → 0.

    sanctions_position — опционально (P1-3). Задана → движение фактора `sanctions`
    клампится доступным ходом с этой позиции. Не задана → прежнее поведение
    (полная интенсивность), обратная совместимость со старыми priors.
    `geopol` НЕ клампится никогда: это страновая риск-премия, она давит и
    отпускает весь рынок сразу и позиции бумаги на санкционной шкале не имеет.

    with_contributions (P2-4) — False (default) возвращает float как раньше; True
    возвращает (total, {factor: вклад в п.п.}). Вклад считается ПОСЛЕ клампа позиции:
    интервал должен строиться на состоявшемся ходе, а не на номинальной интенсивности.
    sum(вклады) совпадает с total до ~1e-14, но НЕ побитово: CPython'овский sum()
    накапливает float иначе, чем `+=` в цикле, даже при одинаковом порядке ключей.
    На округление центра до сотых это не влияет (проверено эталонным прогоном:
    ни одна из 632 ячеек не изменила value).
    """
    total = 0.0
    contributions: dict[str, float] = {}
    for f, beta in betas.items():
        v = factors.get(f, 0)
        if v is None:
            v = 0
        v = float(v)
        if f == "sanctions" and sanctions_position is not None:
            v = effective_sanctions_move(v, sanctions_position)
        part = float(beta) * v
        total += part
        if with_contributions:
            contributions[f] = part
    return (total, contributions) if with_contributions else total


def ci_from_delta(delta: float, r2: float | None,
                  contributions: dict[str, float] | None = None,
                  ) -> tuple[float, float]:
    """
    contributions (P2-4) — {factor: вклад в п.п.}; None → прежняя формула бит-в-бит.

    CI placeholder при отсутствии истории (r2 = null):
      ширина = max(|delta| * 0.4, 5.0) с каждой стороны (минимум ±5 п.п.).
    При наличии r2 — масштабируется по 1/sqrt(r2).
    """
    if contributions is not None:
        # P2-4: ширина складывается из вкладов факторов, каждый со своей относительной
        # неопределённостью. Свёртка КВАДРАТИЧНАЯ, а не сумма модулей: вклады разных
        # факторов не обязаны ошибаться в одну сторону. Потолка нет — измерено, что
        # максимум по живому портфелю 21.8 п.п.; ограничивать нечего, а от
        # патологических бет защищает гард шкалы.
        raw = math.sqrt(sum(
            (abs(float(c)) * FACTOR_BETA_UNCERTAINTY.get(f, FACTOR_BETA_UNCERTAINTY_DEFAULT)) ** 2
            for f, c in contributions.items()
        ))
        half = max(raw, CI_MIN_HALF_WIDTH_PP)
        return (round(delta - half, 2), round(delta + half, 2))

    half_width = max(abs(delta) * CI_LEGACY_DELTA_SHARE, CI_MIN_HALF_WIDTH_PP)
    if r2 is not None and r2 > 0:
        # уверенность тем меньше, чем меньше r2: ширина ~ 1/sqrt(r2), но capped.
        scale = min(1.0 / max(r2, 0.05) ** 0.5, 3.0)
        half_width *= scale
    return (round(delta - half_width, 2), round(delta + half_width, 2))


def is_macro_blindspot(
    ticker: str, betas: dict[str, float], r2: float | None
) -> tuple[bool, str | None]:
    if ticker.upper() in IDIOSYNCRATIC_TICKERS:
        return True, IDIOSYNCRATIC_TICKERS[ticker.upper()]
    if r2 is not None and r2 < 0.3:
        return True, f"low R^2 ({r2:.2f}) in factor regression"
    if betas and all(abs(b) < 0.1 for b in betas.values()):
        return True, "all |beta| < 0.1 — нечувствительна к макрофакторам"
    return False, None


def normalize_betas(betas_in: dict[str, float]) -> dict[str, float]:
    """
    Привести к каноническому списку факторов: отсутствующий фактор → 0.0 (B2).
    """
    out: dict[str, float] = {}
    for f in CANONICAL_FACTORS:
        v = betas_in.get(f, 0.0)
        out[f] = float(v) if v is not None else 0.0
    return out


# ════════════════════════════════════════════════════════════════════════
# P0-1: гард шкалы политических бет + P0-2: гард горизонтного пути дилов
# ════════════════════════════════════════════════════════════════════════


def _sanctions_position(prior: dict[str, Any] | None) -> float | None:
    """
    Читает `sanctions_position` из prior. Отсутствует/не число → None (прежнее
    поведение). Значения вне [0,1] сюда не доходят: их раньше отвергает
    `check_sanctions_positions`. Кламп позиции внутри `effective_sanctions_move` —
    защитный backstop для прямых вызовов функции, не рабочий путь движка.
    """
    if not isinstance(prior, dict):
        return None
    v = prior.get("sanctions_position")
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ════════════════════════════════════════════════════════════════════════
# Phase 4 (V2-A): multiple horizons — блок by_horizon на позицию
# ════════════════════════════════════════════════════════════════════════
#
# Беты SS-1 — месячные, горизонт-независимые (D4-2): считаются один раз, общие на
# все горизонты. От горизонта зависят только factors (factors_by_horizon[hNN]) и,
# при экстраполяции года FCA, CI-инфляция (horizon_coverage из compute_horizon_factors).

DEFAULT_HORIZON_KEY = "h20"  # v1-обёртка: единственный горизонт legacy-входа

DAYS_PER_MONTH = 30.4375  # 365.25 / 12 — как в aggregate_positions.py


# ── Maturity guard (Слой 1 total-return, 2026-07) ──
# Облигация, гасящаяся/оферта ДО конца горизонта H, НЕ переоценивается бетами на H
# (переоценка несуществующей бумаги = двойной счёт с carry-слоем): её price_delta
# на этом горизонте обнуляется с флагом price_delta_zeroed, а весь лайфцикл
# (купоны до события + par + реинвест тела) отдаётся compute_bond_carry.py.

def _parse_iso_date(s: Any) -> date | None:
    if isinstance(s, date):
        return s
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _earliest_date(*candidates: Any) -> date | None:
    parsed = [d for d in (_parse_iso_date(c) for c in candidates) if d is not None]
    return min(parsed) if parsed else None


def _add_months_eom(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _resolve_horizon_end_dates(
    horizon_keys: list[str],
    horizon_ends_in: dict[str, str] | None,
    as_of: date | None,
) -> dict[str, date] | None:
    """
    {hNN: date} для maturity guard: явные horizon_ends (стаб/якорный режим)
    приоритетнее; иначе as_of + NN (конец месяца, §11.0). Ни того ни другого →
    None (guard отключается с warning — не гадаем даты).
    """
    out: dict[str, date] = {}
    for hk in horizon_keys:
        d = _parse_iso_date((horizon_ends_in or {}).get(hk))
        if d is None and as_of is not None and hk[1:].isdigit():
            d = _add_months_eom(as_of, int(hk[1:]))
        if d is not None:
            out[hk] = d
    return out or None


def _bond_zeroed_horizons(
    holding: dict[str, Any],
    horizon_end_dates: dict[str, date] | None,
    as_of: date | None,
) -> dict[str, float] | None:
    """{hNN: t_live_months} для горизонтов, где бумага гасится/оферта до конца."""
    if not horizon_end_dates:
        return None
    if (holding.get("asset_type") or "").lower() != "bond":
        return None
    event = _earliest_date(holding.get("offer_date"), holding.get("maturity_date"))
    if event is None:
        return None
    out: dict[str, float] = {}
    for hk, hend in horizon_end_dates.items():
        if event <= hend:
            t_live = max(0.0, (event - as_of).days / DAYS_PER_MONTH) if as_of else 0.0
            out[hk] = round(t_live, 2)
    return out or None


def _inflate_ci(point: float, lo: float, hi: float, inflation: float) -> tuple[float, float]:
    """Расширить CI вокруг точки в `inflation` раз (точку не двигаем)."""
    return (round(point - (point - lo) * inflation, 2),
            round(point + (hi - point) * inflation, 2))


def _factors_for_horizon(scenario: dict, horizon_key: str) -> dict[str, Any]:
    """factors_by_horizon[hNN] (v2) или плоский factors (v1-fallback)."""
    fbh = scenario.get("factors_by_horizon")
    if isinstance(fbh, dict) and horizon_key in fbh:
        return fbh.get(horizon_key) or {}
    return scenario.get("factors") or {}


def _determine_horizon_keys(
    scenarios: dict[str, dict[str, Any]],
    horizons_arg: list[int] | None,
) -> tuple[list[str], bool]:
    """
    Возвращает (horizon_keys, is_v2). v2 — если хоть один сценарий несёт
    factors_by_horizon: ключи берутся из их объединения. Иначе v1 → один горизонт
    (из --horizons или DEFAULT_HORIZON_KEY).
    """
    keys: set[str] = set()
    has_v2 = False
    for sc in scenarios.values():
        fbh = (sc or {}).get("factors_by_horizon")
        if isinstance(fbh, dict):
            has_v2 = True
            keys.update(fbh.keys())
    if has_v2 and keys:
        return sorted(keys, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0), True
    if horizons_arg:
        return [f"h{h}" for h in sorted(set(horizons_arg))], False
    return [DEFAULT_HORIZON_KEY], False


def _scenario_weight(sc: dict[str, Any], horizon_key: str) -> float:
    """
    Вес сценария на горизонте. `p_by_horizon: {hNN: вес}` приоритетнее скаляра `p`.

    Убеждение о том, какой сценарий реализуется, зависит от срока: на полгода
    вперёд может быть модальным один мир, на два года — другой. Скаляр `p` этого
    выразить не может. Отсутствие блока → прежнее поведение (скаляр, по умолчанию
    0.25 у всех — Pure Shell D1).
    """
    if isinstance(sc, dict):
        pbh = sc.get("p_by_horizon")
        if isinstance(pbh, dict):
            v = pbh.get(horizon_key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return float((sc or {}).get("p", (sc or {}).get("probability", 0.0)))


def _build_by_horizon(
    betas: dict[str, float],
    r2: float | None,
    scenarios: dict[str, dict[str, Any]],
    horizon_keys: list[str],
    horizon_ci_inflation: dict[str, float] | None,
    *,
    money_market: bool = False,
    zeroed_horizons: dict[str, float] | None = None,
    sanctions_position: float | None = None,
) -> dict[str, Any]:
    """
    Считает блок by_horizon: на каждый горизонт — delta_pct_by_scenario,
    expected_pct_pweighted, tail_var_pct/scenario_id. Беты общие на все горизонты.
    zeroed_horizons (maturity guard): {hNN: t_live_months} — на этих горизонтах
    price_delta = 0 (бумага гасится/оферта внутри горизонта; доход — Слой 2).
    """
    infl_map = horizon_ci_inflation or {}
    by_h: dict[str, Any] = {}
    for hk in horizon_keys:
        t_live = (zeroed_horizons or {}).get(hk)
        if t_live is not None:
            zero = {"value": 0.0, "ci_pct": [0.0, 0.0]}
            by_h[hk] = {
                "delta_pct_by_scenario": {sid: dict(zero) for sid in scenarios},
                "expected_pct_pweighted": dict(zero),
                "tail_var_pct": 0.0,
                "tail_var_scenario_id": next(iter(scenarios), None),
                "price_delta_zeroed": "maturity_within_horizon",
                "t_live_months": t_live,
            }
            continue
        delta_by_scenario: dict[str, dict[str, Any]] = {}
        for sid, sc in scenarios.items():
            p = _scenario_weight(sc, hk)
            if money_market:
                value, lo, hi = 0.0, -1.0, 1.0
            else:
                factors = _factors_for_horizon(sc, hk)
                raw_value, contribs = compute_delta_pct(
                    betas, factors, sanctions_position, with_contributions=True
                )
                value = round(raw_value, 2)
                # Гейт по r2, а НЕ по режиму: resolve_betas отдаёт factor_betas_r2 и в
                # priors-режиме. При наличии r2 неопределённость уже измерена
                # эмпирически (1/sqrt(r2)), и априорные множители наложились бы на неё
                # вторым слоем — один источник учтён дважды.
                lo, hi = ci_from_delta(value, r2, None if r2 is not None else contribs)
                infl = float(infl_map.get(hk, 1.0) or 1.0)
                if infl != 1.0:
                    lo, hi = _inflate_ci(value, lo, hi, infl)
            delta_by_scenario[sid] = {"value": value, "ci_pct": [lo, hi], "_p": p}

        expected_value = round(
            sum(d["_p"] * d["value"] for d in delta_by_scenario.values()), 2
        )
        expected_ci = [
            round(sum(d["_p"] * d["ci_pct"][0] for d in delta_by_scenario.values()), 2),
            round(sum(d["_p"] * d["ci_pct"][1] for d in delta_by_scenario.values()), 2),
        ]
        worst_sid, worst = min(
            delta_by_scenario.items(), key=lambda kv: kv[1]["value"]
        )
        delta_out = {
            sid: {"value": d["value"], "ci_pct": d["ci_pct"]}
            for sid, d in delta_by_scenario.items()
        }
        by_h[hk] = {
            "delta_pct_by_scenario": delta_out,
            "expected_pct_pweighted": {"value": expected_value, "ci_pct": expected_ci},
            "tail_var_pct": worst["value"],
            "tail_var_scenario_id": worst_sid,
        }
    return by_h


# ════════════════════════════════════════════════════════════════════════
# SS-1: эмпирические факторные беты через OLS на 24 мес MOEX/CBR истории
# ════════════════════════════════════════════════════════════════════════
#
# Архитектура (робастность — приоритет):
#   • Каждый внешний fetch — best-effort: при сетевой ошибке/нехватке истории
#     бросает исключение, которое ловит вызывающий код → graceful fallback на
#     priors конкретного тикера + warning. Целиком run никогда не падает.
#   • OLS-движок (run_ols), выделение месячных рядов и stitching Brent —
#     чистые функции без сети, тестируются офлайн на синтетике.
#   • Сетевые fetch-функции принимают инъектируемый _get → мокаются в тестах.
#   • priors-режим (default) этот блок НЕ затрагивает.


def _iss_get_json(url: str, timeout: int = HTTP_TIMEOUT) -> dict:
    """GET JSON с ISS/CBR (gzip, stdlib). Бросает на сетевую/HTTP ошибку."""
    req = urllib.request.Request(
        url, headers={"User-Agent": HTTP_USER_AGENT, "Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _rows_to_pairs(payload: dict, block: str, date_col: str, val_col: str,
                   board_col: str | None = None, board: str | None = None
                   ) -> list[tuple[str, float]]:
    """
    Превращает ISS history-блок в [(date_str, value)], отбрасывая нулевые/пустые
    и (опц.) фильтруя по доске. Несколько строк на дату (разные доски) —
    фильтр board решает неоднозначность.
    """
    blk = payload.get(block) or {}
    cols = blk.get("columns") or []
    data = blk.get("data") or []
    try:
        di = cols.index(date_col)
        vi = cols.index(val_col)
    except ValueError:
        return []
    bi = cols.index(board_col) if (board_col and board_col in cols) else None
    pairs: list[tuple[str, float]] = []
    for row in data:
        if bi is not None and board is not None and row[bi] != board:
            continue
        d = row[di]
        v = row[vi]
        if d is None or v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv == 0.0:
            continue
        pairs.append((str(d), fv))
    return pairs


def _monthly_last_level(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """[(YYYY-MM-DD, level)] → {YYYY-MM: последний по дате level в месяце}."""
    by_month: dict[str, tuple[str, float]] = {}
    for d, v in pairs:
        month = d[:7]
        prev = by_month.get(month)
        if prev is None or d > prev[0]:
            by_month[month] = (d, v)
    return {m: dv[1] for m, dv in by_month.items()}


def _levels_to_returns(month_level: dict[str, float]) -> dict[str, float]:
    """{YYYY-MM: level} → {YYYY-MM: % изменение к предыдущему доступному месяцу}."""
    months = sorted(month_level)
    out: dict[str, float] = {}
    for i in range(1, len(months)):
        prev, cur = month_level[months[i - 1]], month_level[months[i]]
        if prev and prev != 0:
            out[months[i]] = (cur / prev - 1.0) * 100.0
    return out


def _levels_to_diffs(month_level: dict[str, float]) -> dict[str, float]:
    """{YYYY-MM: level} → {YYYY-MM: разница в п.п. к предыдущему месяцу} (для ставки)."""
    months = sorted(month_level)
    out: dict[str, float] = {}
    for i in range(1, len(months)):
        out[months[i]] = month_level[months[i]] - month_level[months[i - 1]]
    return out


def _window_months(months: int, end: tuple[int, int]) -> list[tuple[int, int]]:
    """Список (год, месяц) длиной months, заканчивающийся на end включительно."""
    y, m = end
    out: list[tuple[int, int]] = []
    for _ in range(months):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _next_month(ym: tuple[int, int]) -> tuple[int, int]:
    y, m = ym
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _month_end_str(ym: tuple[int, int]) -> str:
    """1-е число СЛЕДУЮЩЕГО месяца как till (ISS отдаёт строго < till)."""
    ny, nm = _next_month(ym)
    return f"{ny:04d}-{nm:02d}-01"


def _date_window_args(months: int, ref: tuple[int, int]) -> tuple[str, str]:
    """from/till ISO-даты окна (months+1 назад от ref до конца ref включительно)."""
    win = _window_months(months + 1, ref)
    y0, m0 = win[0]
    return f"{y0:04d}-{m0:02d}-01", _month_end_str(ref)


# ── Постраничное чтение ISS history (PAGESIZE=100; обязательно для длинных окон) ──

ISS_PAGE = 100
ISS_MAX_PAGES = 80   # backstop: до 8000 строк


def _iss_history_all(url_no_start: str, block: str = "history",
                     _get=_iss_get_json) -> dict:
    """
    Собирает ВСЕ строки history-блока через cursor (&start=N). Без пагинации
    ISS вернёт лишь первые 100 строк (~1 месяц) — на окне 24 мес это критично.
    """
    rows: list = []
    cols: list | None = None
    sep = "&" if "?" in url_no_start else "?"
    for p in range(ISS_MAX_PAGES):
        payload = _get(f"{url_no_start}{sep}start={p * ISS_PAGE}")
        blk = payload.get(block) or {}
        if cols is None:
            cols = blk.get("columns") or []
        data = blk.get("data") or []
        if not data:
            break
        rows.extend(data)
        if len(data) < ISS_PAGE:
            break
    return {block: {"columns": cols or [], "data": rows}}


# ── Fetchers (best-effort, мокабельны через _get) ──

def fetch_moex_share_history(ticker: str, months: int = REGRESSION_MONTHS,
                             ref: tuple[int, int] | None = None,
                             _get=_iss_get_json) -> dict[str, float]:
    """{YYYY-MM: % мес. доходность акции} по TQBR-доске. Бросает при пустой истории."""
    if ref is None:
        raise ValueError("ref (год, месяц) обязателен — детерминизм без Date.now()")
    frm, till = _date_window_args(months, ref)
    url = (f"{ISS_BASE}/history/engines/stock/markets/shares/securities/{ticker}.json"
           f"?from={frm}&till={till}&iss.meta=off"
           f"&history.columns=BOARDID,TRADEDATE,CLOSE,LEGALCLOSEPRICE")
    payload = _iss_history_all(url, _get=_get)
    pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "CLOSE",
                           board_col="BOARDID", board="TQBR")
    if not pairs:
        # запасной столбец цены закрытия
        pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "LEGALCLOSEPRICE",
                               board_col="BOARDID", board="TQBR")
    if not pairs:
        raise IOError(f"{ticker}: пустая история MOEX shares")
    return _levels_to_returns(_monthly_last_level(pairs))


def fetch_moex_currency_history(secid: str, months: int = REGRESSION_MONTHS,
                                ref: tuple[int, int] | None = None,
                                _get=_iss_get_json) -> dict[str, float]:
    """{YYYY-MM: % мес. изменение валютной пары} по selt/CETS."""
    if ref is None:
        raise ValueError("ref обязателен")
    frm, till = _date_window_args(months, ref)
    url = (f"{ISS_BASE}/history/engines/currency/markets/selt/securities/{secid}.json"
           f"?from={frm}&till={till}&iss.meta=off"
           f"&history.columns=BOARDID,TRADEDATE,CLOSE")
    payload = _iss_history_all(url, _get=_get)
    pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "CLOSE",
                           board_col="BOARDID", board="CETS")
    if not pairs:  # доска не всегда CETS — берём любые ненулевые
        pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "CLOSE")
    if not pairs:
        raise IOError(f"{secid}: пустая история MOEX currency")
    return _levels_to_returns(_monthly_last_level(pairs))


def _cbr_currency_fetch(code: str, from_ddmmyyyy: str, to_ddmmyyyy: str,
                        timeout: int = HTTP_TIMEOUT) -> list[tuple[str, float]]:
    """CBR XML_dynamic → [(YYYY-MM-DD, курс)]. Value делится на Nominal."""
    import xml.etree.ElementTree as ET
    url = (f"{CBR_DYNAMIC_URL}?date_req1={from_ddmmyyyy}&date_req2={to_ddmmyyyy}"
           f"&VAL_NM_RQ={code}")
    req = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)  # XML-декларация windows-1251 — ET декодирует сам
    out: list[tuple[str, float]] = []
    for rec in root.findall("Record"):
        d = rec.get("Date") or ""          # DD.MM.YYYY
        v = (rec.findtext("Value") or "").replace(" ", "").replace(",", ".")
        nom = (rec.findtext("Nominal") or "1").replace(",", ".")
        if len(d) != 10 or not v:
            continue
        try:
            val = float(v) / float(nom or "1")
        except (ValueError, ZeroDivisionError):
            continue
        out.append((f"{d[6:10]}-{d[3:5]}-{d[0:2]}", val))
    return out


def fetch_cbr_currency_history(code: str, months: int = REGRESSION_MONTHS,
                               ref: tuple[int, int] | None = None,
                               _get=None) -> dict[str, float]:
    """
    {YYYY-MM: % мес. изменение официального курса ЦБ}. Надёжный источник FX
    (в отличие от приостановленного USD/RUB на MOEX).
    _get (опц., тесты): callable(from_ddmmyyyy, to_ddmmyyyy) → [(YYYY-MM-DD, курс)].
    """
    if ref is None:
        raise ValueError("ref обязателен")
    win = _window_months(months + 1, ref)
    y0, m0 = win[0]
    ny, nm = _next_month(ref)
    frm = f"01/{m0:02d}/{y0:04d}"
    to = f"01/{nm:02d}/{ny:04d}"
    fetch = _get or (lambda f, t: _cbr_currency_fetch(code, f, t))
    pairs = fetch(frm, to)
    if not pairs:
        raise IOError(f"CBR {code}: пустой ответ XML_dynamic")
    return _levels_to_returns(_monthly_last_level(pairs))


def _brent_secid(year: int, month: int) -> str:
    """SECID месячного Brent-фьючерса FORTS, напр. (2026, 6) → 'BRM6' (= BR-6.26)."""
    return f"BR{FUTURES_MONTH_CODES[month - 1]}{year % 10}"


def _brent_front_for_month(ym: tuple[int, int]) -> str:
    """
    Front-контракт, торгуемый в течение месяца ym. На MOEX BR-X.YY экспирируется
    ~1-го числа месяца X, т.е. front в течение месяца m — это контракт BR-(m+1).
    Пример: в июне 2026 front = BRN6 (BR-7.26, экспирация ~1 июля).
    """
    return _brent_secid(*_next_month(ym))


def fetch_moex_brent_history(months: int = REGRESSION_MONTHS,
                             ref: tuple[int, int] | None = None,
                             _get=_iss_get_json) -> dict[str, float]:
    """
    {YYYY-MM: % мес. изменение Brent} по FORTS-фьючерсам.

    Для уровня месяца m берём month-end settle контракта BR-(m+1) — он front
    в течение m и near-expiry в конце m (BR-X.YY гасится ~1-го числа месяца X),
    т.е. сошёлся к споту → надёжное значение. Доходности — между соседними
    near-expiry уровнями (roll-спред смежных контрактов мал, ~1-2%). Так
    избегаем устаревших settle далёких контрактов (которые в начале жизни
    могут давать фейковые ±десятки %).
    """
    if ref is None:
        raise ValueError("ref обязателен")
    levels: dict[str, float] = {}
    for (y, m) in _window_months(months + 1, ref):
        secid = _brent_front_for_month((y, m))  # BR-(m+1), near-expiry в конце m
        frm = f"{y:04d}-{m:02d}-01"
        till = _month_end_str((y, m))
        url = (f"{ISS_BASE}/history/engines/futures/markets/forts/securities/{secid}.json"
               f"?from={frm}&till={till}&iss.meta=off"
               f"&history.columns=TRADEDATE,SETTLEPRICE,CLOSE")
        try:
            payload = _iss_history_all(url, _get=_get)
        except Exception:
            continue
        pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "SETTLEPRICE")
        if not pairs:
            pairs = _rows_to_pairs(payload, "history", "TRADEDATE", "CLOSE")
        ml = _monthly_last_level(pairs)
        key = f"{y:04d}-{m:02d}"
        if key in ml:
            levels[key] = ml[key]
    if len(levels) < 2:
        raise IOError("Brent: недостаточно фьючерсной истории для стичинга")
    return _levels_to_returns(levels)


def _cbr_soap_envelope(from_date: str, to_date: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
        ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><KeyRate xmlns="http://web.cbr.ru/">'
        f'<fromDate>{from_date}</fromDate><ToDate>{to_date}</ToDate>'
        '</KeyRate></soap:Body></soap:Envelope>'
    ).encode("utf-8")


def _cbr_get_keyrate(from_date: str, to_date: str, timeout: int = HTTP_TIMEOUT
                     ) -> list[tuple[str, float]]:
    """SOAP POST к CBR KeyRate → [(YYYY-MM-DD, rate)]. Бросает при ошибке."""
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(
        CBR_SOAP_ENDPOINT, data=_cbr_soap_envelope(from_date, to_date),
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": "http://web.cbr.ru/KeyRate",
                 "User-Agent": HTTP_USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    out: list[tuple[str, float]] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag != "KR":
            continue
        dt = rate = None
        for child in elem:
            ct = child.tag.rsplit("}", 1)[-1]
            if ct == "DT":
                dt = (child.text or "").strip()[:10]
            elif ct == "Rate":
                rate = (child.text or "").strip()
        if dt and rate:
            try:
                out.append((dt, float(rate.replace(",", "."))))
            except ValueError:
                continue
    return out


def fetch_cbr_rate_history(months: int = REGRESSION_MONTHS,
                           ref: tuple[int, int] | None = None,
                           _get=None) -> dict[str, float]:
    """
    {YYYY-MM: Δ ключевой ставки ЦБ в п.п. к предыдущему месяцу}.
    _get (опц.) — инъекция для тестов: callable(from,to) → [(date,rate)].
    """
    if ref is None:
        raise ValueError("ref обязателен")
    win = _window_months(months + 1, ref)
    y0, m0 = win[0]
    y1, m1 = ref
    fetch = _get or _cbr_get_keyrate
    pairs = fetch(f"{y0:04d}-{m0:02d}-01", f"{y1:04d}-{m1:02d}-28")
    if not pairs:
        raise IOError("CBR KeyRate: пустой ответ")
    # Ставка — ступенчатая: month-end level = последняя известная ставка ≤ конца месяца.
    month_level: dict[str, float] = {}
    spairs = sorted(pairs)
    for (y, m) in win:
        key = f"{y:04d}-{m:02d}"
        end = f"{y:04d}-{m:02d}-31"
        level = None
        for d, r in spairs:
            if d <= end:
                level = r
            else:
                break
        if level is not None:
            month_level[key] = level
    return _levels_to_diffs(month_level)


def build_factor_matrix(months: int, ref: tuple[int, int],
                        fetchers: dict | None = None) -> dict[str, dict[str, float]]:
    """
    Строит {factor: {YYYY-MM: движение}} по REGRESSION_FACTORS. Каждый фактор
    независим и best-effort: упавший пропускается (regression пойдёт по остальным).
    fetchers — инъекция в тестах: {'brent': fn, 'usdrub': fn, 'cnyrub': fn, 'cbr_rate': fn}.
    """
    fetchers = fetchers or {}
    matrix: dict[str, dict[str, float]] = {}

    def _try(name: str, fn) -> None:
        try:
            series = fn()
            if series:
                matrix[name] = series
        except Exception:
            pass  # фактор недоступен — пропускаем, не валим остальные

    _try("brent", fetchers.get("brent",
         lambda: fetch_moex_brent_history(months, ref)))
    # FX — официальные курсы ЦБ (USD/RUB на MOEX приостановлен, см. CURRENCY_SECID)
    _try("usdrub", fetchers.get("usdrub",
         lambda: fetch_cbr_currency_history(CBR_CURRENCY_CODES["usdrub"], months, ref)))
    _try("cnyrub", fetchers.get("cnyrub",
         lambda: fetch_cbr_currency_history(CBR_CURRENCY_CODES["cnyrub"], months, ref)))
    _try("cbr_rate", fetchers.get("cbr_rate",
         lambda: fetch_cbr_rate_history(months, ref)))
    return matrix


def run_ols(y: list[float], x_cols: dict[str, list[float]]) -> tuple[dict[str, float], float]:
    """
    OLS с константой: y ~ const + Σ β_f · x_f (numpy.linalg.lstsq, D-B).
    Возвращает ({factor: β}, R²). R² против среднего (классический).
    Бросает ImportError, если numpy недоступен.
    """
    import numpy as np  # lazy: только в moex-режиме

    factor_names = list(x_cols)
    n = len(y)
    if n == 0 or not factor_names:
        return {}, 0.0
    A = np.column_stack([np.ones(n)] + [np.asarray(x_cols[f], dtype=float)
                                        for f in factor_names])
    yv = np.asarray(y, dtype=float)
    coef, _res, _rank, _sv = np.linalg.lstsq(A, yv, rcond=None)
    pred = A @ coef
    ss_res = float(((yv - pred) ** 2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    betas = {f: float(coef[i + 1]) for i, f in enumerate(factor_names)}  # пропускаем const
    return betas, float(r2)


def compute_regression_betas(
    ticker: str,
    factor_matrix: dict[str, dict[str, float]],
    prior: dict[str, Any],
    months: int = REGRESSION_MONTHS,
    ref: tuple[int, int] | None = None,
    share_fetcher=None,
) -> tuple[dict[str, float], float, list[str], int] | None:
    """
    Эмпирические беты тикера: OLS месячной доходности на факторных рядах.
    Возвращает (full_betas, r2, empirical_factors, n_dropped) или None при
    недостатке данных / вырождении регрессии.

    full_betas — все CANONICAL_FACTORS: регрессированные перекрывают priors,
    нерегрессированные (sanctions/geopol/xauusd и упавшие факторы) — из priors.
    n_dropped — сколько месяцев-выбросов исключено (неадаптированные сплиты).
    share_fetcher — инъекция в тестах: callable() → {YYYY-MM: return}.
    """
    if not factor_matrix:
        return None
    stock = (share_fetcher or
             (lambda: fetch_moex_share_history(ticker, months, ref)))()
    if not stock:
        return None

    # Выравнивание по общим месяцам: пересечение акции и ВСЕХ доступных факторов
    common = set(stock)
    for series in factor_matrix.values():
        common &= set(series)
    common_sorted = sorted(common)
    if len(common_sorted) < MIN_REGRESSION_OBS:
        return None

    # Гард 1: исключаем месяцы-выбросы (|доходность| > порога — неадаптированный сплит)
    clean = [mo for mo in common_sorted if abs(stock[mo]) <= OUTLIER_RETURN_PCT]
    n_dropped = len(common_sorted) - len(clean)
    if len(clean) < MIN_REGRESSION_OBS:
        return None

    y = [stock[mo] for mo in clean]
    x_cols = {f: [factor_matrix[f][mo] for mo in clean] for f in factor_matrix}
    betas, r2 = run_ols(y, x_cols)

    # Гард 2: вырожденная регрессия (коллинеарность/короткая история) → откат на priors
    if any(abs(b) > MAX_ABS_BETA for b in betas.values()):
        return None

    full = normalize_betas(prior.get("factor_betas") or {})  # старт от priors
    for f, b in betas.items():
        if f in CANONICAL_FACTORS:
            full[f] = b  # эмпирическое значение перекрывает prior
    return full, r2, sorted(betas), n_dropped


def _ref_month_from_snapshot(snapshot: dict[str, Any]) -> tuple[int, int]:
    """
    Опорный месяц окна регрессии — последний ПОЛНЫЙ месяц.
    Берём дату снапшота (as_of_date/date/snapshot_date), иначе текущую,
    и откатываемся на 1 месяц назад (текущий месяц обычно неполный).
    """
    raw = (snapshot.get("as_of_date") or snapshot.get("date")
           or snapshot.get("snapshot_date") or "")
    y = m = None
    if isinstance(raw, str) and len(raw) >= 7:
        try:
            y, m = int(raw[0:4]), int(raw[5:7])
        except ValueError:
            y = m = None
    if y is None:
        today = date.today()
        y, m = today.year, today.month
    # на один месяц назад — последний завершённый месяц
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return (y, m)


def resolve_betas(
    ticker: str,
    prior: dict[str, Any],
    regression_mode: str,
    factor_matrix: dict[str, dict[str, float]] | None,
    months: int,
    ref: tuple[int, int] | None,
    warnings: list[str],
) -> tuple[dict[str, float], str, float | None]:
    """
    Единая точка получения (betas, method, r2). priors-режим → ровно прежнее
    поведение. moex-режим → попытка OLS с graceful fallback на priors тикера.
    """
    prior_betas = normalize_betas(prior.get("factor_betas") or {})
    prior_method = prior.get("factor_betas_method") or "sector prior (источник не указан)"
    prior_r2 = prior.get("factor_betas_r2")

    if regression_mode != "moex" or not factor_matrix:
        return prior_betas, prior_method, prior_r2

    try:
        res = compute_regression_betas(ticker, factor_matrix, prior, months, ref)
    except Exception as e:  # сеть/парсинг/numpy — не валим run
        warnings.append(f"{ticker}: OLS не удался ({e}) → priors")
        return prior_betas, prior_method, prior_r2

    if res is None:
        warnings.append(
            f"{ticker}: OLS не дал надёжных бет (мало истории / выбросы / "
            f"вырождение) → priors"
        )
        return prior_betas, prior_method, prior_r2

    betas, r2, empirical, n_dropped = res
    drop_note = f", искл. {n_dropped} выбросов" if n_dropped else ""
    method = f"OLS MOEX {months}mo (эмпирические: {', '.join(empirical)}{drop_note}; " \
             f"прочие из priors)"
    return betas, method, round(r2, 4)


def compute_per_position(
    snapshot: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
    priors: dict[str, dict[str, Any]],
    regression_mode: str,
    ref_month: tuple[int, int] | None = None,
    horizons: list[int] | None = None,
    horizon_ci_inflation: dict[str, float] | None = None,
    horizon_ends: dict[str, str] | None = None,
    political_scale_check: str = "error",
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """
    Возвращает (per_position_dict, warnings, unmapped_tickers).

    unmapped_tickers — список {ticker, weight_pct, reason} для позиций,
    которые попали в snapshot, но были выкинуты из расчёта (нет priors,
    отсутствует ticker и т.п.). Передаётся в pre-emit checklist
    как обязательное поле итогового YAML.

    ref_month — (год, месяц) последнего полного месяца для окна регрессии
    (moex-режим). None → из даты снапшота, иначе текущий месяц.

    horizons — список месяцев (V2-A). Источник горизонтов: сценарии с
    factors_by_horizon (v2) задают ключи сами; v1-вход (плоский factors) →
    обёртка в один горизонт (--horizons или h20) + warning.
    horizon_ci_inflation — {hNN: множитель} из horizon_coverage (D4-3).
    horizon_ends — {hNN: YYYY-MM-DD} для maturity guard (из стаба/якорного
    режима); отсутствует → даты выводятся из as_of_date снапшота + NN.

    political_scale_check — режим гарда шкалы политических бет (P0-1):
    "error" (default, отказ считать) | "warn" | "off".
    """
    holdings = snapshot.get("holdings") or []
    total_value = compute_total_value(holdings)
    if total_value <= 0:
        raise SystemExit("ERROR: суммарная стоимость портфеля = 0, нечего считать")

    warnings: list[str] = []

    # ── Горизонты (V2-A): v2-сценарии задают factors_by_horizon, v1 → один горизонт ──
    horizon_keys, is_v2 = _determine_horizon_keys(scenarios, horizons)
    if not is_v2:
        warnings.append(
            f"v1-вход (factors без factors_by_horizon) → обёрнут в by_horizon."
            f"{{{','.join(horizon_keys)}}}"
        )

    # ── P0-1/P0-2/P1-3: гарды контракта priors (до любых расчётов) ──
    # Структура и числовая валидность проверяются ВСЕГДА: --political-scale-check
    # гейтит проверку ШКАЛЫ, а не формы. Ошибки собираются и предъявляются РАЗОМ,
    # иначе пользователь чинит их по одной за прогон, теряя накопленные warnings.
    contract_errors: list[str] = check_priors_structure(priors, holdings)
    scale_errors: list[str] = []
    # Гейта «структура сломана → остальное не проверяем» здесь нет намеренно:
    # каждый гард сам устойчив к битой записи, а гейт возвращал бы ровно то, ради
    # чего писалась агрегация — починил одно, перезапустил, узнал про второе.
    # Исключение одно: priors вообще не dict — тогда итерировать нечего.
    if isinstance(priors, dict):
        contract_errors.extend(check_betas_numeric(priors, holdings))
        if political_scale_check != "off":
            scale_errors, scale_warns = check_political_beta_scale(priors, holdings)
            warnings.extend(scale_warns)
            if political_scale_check == "error":
                contract_errors.extend(scale_errors)
            else:
                warnings.extend(scale_errors)
        pos_errors, pos_warns = check_sanctions_positions(priors, holdings)
        warnings.extend(pos_warns)
        contract_errors.extend(pos_errors)
    warnings.extend(check_political_horizon_path(scenarios))
    w_errors, w_warns = check_scenario_weights(scenarios, horizon_keys)
    warnings.extend(w_warns)
    contract_errors.extend(w_errors)

    if contract_errors:
        msg = ["ERROR: " + "\n       ".join(contract_errors)]
        if warnings:
            msg.append("       Собранные предупреждения этого прогона:\n       "
                       + "\n       ".join(warnings))
        # Подсказку про флаг печатаем ТОЛЬКО когда он действительно что-то меняет:
        # к битой форме, нечисловым бетам и sanctions_position он отношения не имеет.
        if scale_errors and political_scale_check == "error":
            msg.append("       Осознанно оставить шкалу как есть: "
                       "--political-scale-check warn")
        raise SystemExit("\n".join(msg))

    per_position: dict[str, Any] = {}
    unmapped_tickers: list[dict[str, Any]] = []

    # ── Maturity guard: даты концов горизонтов (для обнуления price_delta бондов) ──
    as_of = _parse_iso_date(
        snapshot.get("as_of_date") or snapshot.get("date") or snapshot.get("snapshot_date")
    )
    horizon_end_dates = _resolve_horizon_end_dates(horizon_keys, horizon_ends, as_of)
    if horizon_end_dates is None:
        warnings.append(
            "Maturity guard ОТКЛЮЧЁН: нет as_of_date в снапшоте и не передан "
            "--horizon-ends → price_delta бумаг, гасящихся внутри горизонта, "
            "НЕ обнулён (риск двойного счёта со Слоем 2 compute_bond_carry)"
        )
    zeroed_summary: list[str] = []

    # ── moex-режим: однократно строим факторную матрицу (общая для всех тикеров) ──
    factor_matrix: dict[str, dict[str, float]] | None = None
    if regression_mode == "moex":
        try:
            import numpy  # noqa: F401  — ранняя проверка зависимости
        except ImportError:
            sys.stderr.write(
                "WARNING: numpy не установлен — OLS невозможен, откат на priors. "
                "Установить: pip install numpy --break-system-packages\n"
            )
            warnings.append("numpy недоступен → regression-mode=moex деградировал в priors")
            regression_mode = "priors"
        else:
            ref = ref_month or _ref_month_from_snapshot(snapshot)
            factor_matrix = build_factor_matrix(REGRESSION_MONTHS, ref)
            if not factor_matrix:
                warnings.append(
                    "Не удалось построить ни одного факторного ряда (сеть/ISS) → priors"
                )
            else:
                built = ", ".join(sorted(factor_matrix))
                sys.stderr.write(f"moex: факторные ряды построены: {built}\n")
                # ref в замыкание для resolve_betas
                snapshot = dict(snapshot)
                snapshot["_regression_ref"] = ref

    # Ноги одной бумаги по разным счетам — в одну запись ДО расчёта: ключ
    # per_position один на тикер, иначе вторая нога затирает первую.
    merged_holdings, merge_warns, merge_dropped = merge_holding_legs(holdings)
    warnings.extend(merge_warns)
    unmapped_tickers.extend(merge_dropped)

    published_value = 0.0

    for holding in merged_holdings:
        excluded, reason = is_excluded(holding)
        if excluded:
            continue

        ticker = (holding.get("ticker") or "").upper()
        value_rub = float(holding.get("value_rub") or 0)
        weight_pct = round(value_rub / total_value * 100, 4)
        if not ticker:
            warnings.append(f"holding без ticker (id={holding.get('id')}) — пропускаю")
            unmapped_tickers.append({
                "ticker": None,
                "weight_pct": weight_pct,
                "reason": f"missing ticker (id={holding.get('id')})",
            })
            continue
        on_iis = bool(holding.get("on_iis", False)) or holding.get("account") == "iis_3"
        asset_type = (holding.get("asset_type") or "").lower()

        # --- Money-market: специальная ветка, priors не нужны ---
        is_mm = is_money_market(ticker, asset_type)
        if is_mm:
            betas = betas_for_money_market()
            method = "money-market — нечувствителен к рассматриваемым факторам"
            r2 = None
            blind = False
            blind_reason = None
        else:
            prior = priors.get(ticker)
            if prior is None:
                warnings.append(
                    f"{ticker}: нет priors в betas-priors.json — пропускаю "
                    f"(weight_pct={weight_pct})"
                )
                unmapped_tickers.append({
                    "ticker": ticker,
                    "weight_pct": weight_pct,
                    "reason": "no priors in betas-priors.json",
                })
                continue
            # priors-режим → прежнее поведение; moex → OLS с fallback на priors (SS-1)
            betas, method, r2 = resolve_betas(
                ticker, prior, regression_mode, factor_matrix,
                REGRESSION_MONTHS, snapshot.get("_regression_ref"), warnings,
            )
            blind, blind_reason = is_macro_blindspot(ticker, betas, r2)

        # Maturity guard: бумага гасится/оферта до конца горизонта → price_delta
        # этого горизонта = 0 (лайфцикл считает Слой 2, compute_bond_carry.py).
        zeroed = _bond_zeroed_horizons(holding, horizon_end_dates, as_of)
        if zeroed:
            zeroed_summary.append(f"{ticker}({','.join(sorted(zeroed))})")

        # V2-A: блок by_horizon — дельты/expected/tail на каждый горизонт.
        # Беты общие на все горизонты (D4-2); от горизонта зависят factors_by_horizon.
        # P1-3: позиция бумаги на санкционной шкале (опционально; None → прежнее
        # поведение). Валидация и warning'и собираются отдельным проходом ниже.
        s_pos = _sanctions_position(prior if not is_mm else None)

        by_horizon = _build_by_horizon(
            betas, r2, scenarios, horizon_keys, horizon_ci_inflation,
            money_market=is_mm, zeroed_horizons=zeroed,
            sanctions_position=s_pos,
        )

        entry: dict[str, Any] = {
            "weight_pct": weight_pct,
            "on_iis": on_iis,
            "factor_betas": betas,
            "factor_betas_method": method,
            "factor_betas_r2": r2,
            "by_horizon": by_horizon,
        }
        if s_pos is not None:
            entry["sanctions_position"] = s_pos
        # Класс актива, по которому работали гарды шкалы (prior приоритетнее снапшота):
        # пересчёт из полного файла проверяет шкалу по тому же классу, что сборка.
        at_used = _asset_type_of(ticker, priors.get(ticker) or {}, {ticker: holding})
        if at_used:
            entry["asset_type"] = at_used
        if blind:
            entry["macro_blindspot"] = True
            entry["macro_blindspot_reason"] = blind_reason

        per_position[ticker] = entry
        published_value += value_rub

    if zeroed_summary:
        warnings.append(
            f"Maturity guard: price_delta обнулён у {len(zeroed_summary)} бумаг(и) "
            f"с погашением/офертой внутри горизонта: {'; '.join(zeroed_summary)}. "
            f"Их купоны/par/реинвест считает Слой 2 (compute_bond_carry.py)."
        )

    # Контроль покрытия — должен быть ≥99% от unblocked non-cash positions.
    # Cash (RUB на брокерском счёте) исключён по дизайну, в знаменателе не учитываем.
    eligible_value = 0.0
    for h in holdings:
        excluded, reason = is_excluded(h)
        if excluded and reason == "cash_rub":
            continue
        if h.get("is_blocked", False):
            continue
        eligible_value += float(h.get("value_rub") or 0)

    # Покрытие считаем по стоимости, РЕАЛЬНО опубликованной в per_position, а не по
    # членству тикера: членство слепо к потерянной ноге расщеплённой позиции —
    # обе ноги числились бы покрытыми при опубликованной одной.
    coverage_pct = published_value / eligible_value * 100 if eligible_value > 0 else 0
    if coverage_pct < 99.0:
        warnings.append(
            f"Покрытие per_position = {coverage_pct:.1f}% от non-cash unblocked "
            f"(< 99%): опубликовано {published_value:,.0f} ₽ из {eligible_value:,.0f} ₽. "
            f"Проверь priors на пропущенные тикеры и unmapped_tickers."
        )

    return per_position, warnings, unmapped_tickers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute per_position block for stress-test YAML (schema v2, by_horizon)."
    )
    parser.add_argument("--snapshot", required=True, type=Path, help="Portfolio snapshot JSON")
    parser.add_argument(
        "--scenarios",
        required=True,
        type=Path,
        help="YAML с блоком scenarios: (минимум name/p/factors на каждый ID)",
    )
    parser.add_argument(
        "--priors",
        required=True,
        type=Path,
        help="JSON с factor_betas priors по тикерам",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Куда писать YAML-фрагмент per_position"
    )
    parser.add_argument(
        "--regression-mode",
        choices=["priors", "moex"],
        default="priors",
        help="priors (default, ручные беты) | moex (эмпирические беты через OLS "
             "на 24 мес MOEX/CBR истории; требует numpy + сеть; SS-1)",
    )
    parser.add_argument(
        "--horizons", default=None,
        help="V2-A: список горизонтов в месяцах через запятую (для v1-входа-обёртки; "
             "v2-сценарии с factors_by_horizon задают горизонты сами). Default: 20",
    )
    parser.add_argument(
        "--horizon-coverage", type=Path, default=None,
        help="JSON horizon_coverage из compute_horizon_factors.py — берётся ci_inflation "
             "на горизонт (экстраполяция года FCA → расширение CI).",
    )
    parser.add_argument(
        "--political-scale-check",
        choices=["error", "warn", "off"],
        default="error",
        help="P0-1: гард шкалы бет sanctions/geopol (β — п.п. цены на 1.0 единицы "
             "интенсивности). error (default) — отказ считать при долевой шкале; "
             "warn — посчитать и предупредить; off — не проверять.",
    )
    parser.add_argument(
        "--horizon-ends", type=Path, default=None,
        help="JSON {hNN: YYYY-MM-DD} для maturity guard (обнуление price_delta "
             "бумаг, гасящихся внутри горизонта). Default: horizon_ends из "
             "scenarios-файла, иначе as_of_date снапшота + NN (конец месяца).",
    )
    args = parser.parse_args()

    if not args.snapshot.exists():
        sys.stderr.write(f"ERROR: snapshot не найден: {args.snapshot}\n")
        return 2
    if not args.scenarios.exists():
        sys.stderr.write(f"ERROR: scenarios не найден: {args.scenarios}\n")
        return 2
    if not args.priors.exists():
        sys.stderr.write(f"ERROR: priors не найден: {args.priors}\n")
        return 2

    with args.snapshot.open("r", encoding="utf-8") as f:
        snapshot = json.load(f)

    scenarios_doc = load_yaml_minimal(args.scenarios)
    if "scenarios" in scenarios_doc:
        scenarios = scenarios_doc["scenarios"]
    else:
        scenarios = scenarios_doc
    if not isinstance(scenarios, dict):
        sys.stderr.write(
            "ERROR: scenarios должны быть dict с ключами Sc-X_label, не list. "
            "См. references/output-template.md (схема v1).\n"
        )
        return 2

    with args.priors.open("r", encoding="utf-8") as f:
        priors = json.load(f)
    if not isinstance(priors, dict):
        sys.stderr.write(
            "ERROR: priors должен быть JSON-объектом {тикер: {...}}, получен "
            f"{type(priors).__name__}.\n"
        )
        return 2


    horizons = None
    if args.horizons:
        horizons = sorted({int(t) for t in args.horizons.split(",") if t.strip()})

    horizon_ci_inflation: dict[str, float] | None = None
    if args.horizon_coverage:
        with args.horizon_coverage.open("r", encoding="utf-8") as f:
            cov_doc = json.load(f)
        cov = cov_doc.get("horizon_coverage", cov_doc)
        horizon_ci_inflation = {
            hk: float(v.get("ci_inflation", 1.0)) if isinstance(v, dict) else float(v)
            for hk, v in cov.items()
        }

    # Maturity guard: явные даты концов горизонтов — файл → scenarios-doc → (fallback
    # внутри compute_per_position: as_of_date снапшота + NN, конец месяца).
    horizon_ends: dict[str, str] | None = None
    if args.horizon_ends:
        with args.horizon_ends.open("r", encoding="utf-8") as f:
            he_doc = json.load(f)
        horizon_ends = he_doc.get("horizon_ends", he_doc)
    elif isinstance(scenarios_doc, dict) and isinstance(scenarios_doc.get("horizon_ends"), dict):
        horizon_ends = scenarios_doc["horizon_ends"]

    # Устаревший фрагмент от прошлого (возможно, неверного) прогона удаляем ДО
    # расчёта: рабочий процесс — «прочитать фрагмент и скопировать в YAML», и
    # подхватить старый файл после красного прогона слишком легко. Делаем это
    # ПОСЛЕ разбора всех входов: иначе опечатка в --horizon-coverage сносила бы
    # файл по --output.
    for name, other in (("--snapshot", args.snapshot), ("--scenarios", args.scenarios),
                        ("--priors", args.priors)):
        if args.output.resolve() == other.resolve():
            sys.stderr.write(f"ERROR: --output совпадает с {name} — отказ.\n")
            return 2
    if args.output.is_dir():
        sys.stderr.write(f"ERROR: --output указывает на директорию: {args.output}\n")
        return 2
    if args.output.exists():
        args.output.unlink()

    try:
        per_position, warnings, unmapped_tickers = compute_per_position(
            snapshot=snapshot,
            scenarios=scenarios,
            priors=priors,
            regression_mode=args.regression_mode,
            horizons=horizons,
            horizon_ci_inflation=horizon_ci_inflation,
            horizon_ends=horizon_ends,
            political_scale_check=args.political_scale_check,
        )
    except SystemExit as e:
        # Отказ контракта priors/снапшота — тот же код возврата, что у остальных
        # отказов main() (2), а не 1 от SystemExit со строкой.
        if isinstance(e.code, str):
            sys.stderr.write(e.code.rstrip("\n") + "\n")
            return 2
        raise

    fragment = {
        "per_position": per_position,
        "unmapped_tickers": unmapped_tickers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        f.write("# Auto-generated by compute_per_position.py — copy into final stress-YAML\n")
        f.write("# unmapped_tickers — обязательное поле финального YAML (Pre-emit checklist).\n")
        f.write(dump_yaml(fragment))

    print(f"OK: per_position fragment → {args.output}")
    print(f"   Покрыто позиций: {len(per_position)}")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  • {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
