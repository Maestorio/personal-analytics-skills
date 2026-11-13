#!/usr/bin/env python3
"""
input_contract.py — контракт входа стресс-теста и его гарды (PSS-7).

Здесь лежит то, что движок ПРЕДПОЛАГАЕТ о своих входах, и проверки, что эти
предположения выполнены: канонический список факторов, отбор holdings, которые
вообще участвуют в расчёте, классификация класса актива и шесть гардов
контракта (структура priors, числовая валидность бет, шкала политических бет,
позиция на санкционной шкале, горизонтный путь дилов, веса сценариев).

Почему отдельным модулем. `compute_per_position.py` перевалил за 1700 строк, и
правки хирургией по нему уже дважды выходили боком: один раз заменой региона
была потеряна целая функция `check_sanctions_positions` (поймали тесты), другой
раз разделение диффа по ханкам собрало синтаксически битую версию. Гарды —
самодостаточный слой без обратных зависимостей, его выделение уменьшает
поверхность таких правок (PSS-7).

Направление зависимостей — строго одностороннее: этот модуль НЕ импортирует
`compute_per_position`, только наоборот. Поэтому сюда переехали и примитивы,
которые нужны и гардам, и расчёту: `is_excluded`, `is_money_market`,
`CANONICAL_FACTORS`, `POSITION_REQUIRED_BETA`. Они реэкспортируются обратно в
`compute_per_position`, так что внешний API не изменился.

Перенос механический: тела функций не редактировались.
"""
from __future__ import annotations

import math
from typing import Any

# Канонический список факторов (B2). Порядок важен для воспроизводимого вывода.
CANONICAL_FACTORS = ["sanctions", "geopol", "cbr_rate", "usdrub", "cnyrub", "brent", "xauusd"]


# Money-market funds — нечувствительны к рассматриваемым факторам (см. SKILL.md Шаг 3.6, B3).
MONEY_MARKET_TICKERS = {"TPAY", "TMON", "LQDT", "SBMM"}


# ── P0-1: контракт единиц политических факторов ──
# ЕДИНОЕ правило для ВСЕХ факторов: β — процентные пункты цены на ОДНУ единицу
# фактора в его собственной единице. Для sanctions/geopol единица — интенсивность
# 1.0 по шкале [-1..+1], значит бета банков ≈ -35 (не -0.35).
#
# Историческая долевая запись («доля цены на единицу») отличается ровно в 100 раз и
# молча зануляет политический канал: прогоны 2026-07-15/23 записали SBER
# β_sanctions=-0.35 → полная разрядка (intensity -0.9) дала +0.32 п.п. вместо
# +31.5, из-за чего порядок сценариев перевернулся (эскалация A стала «лучшим»
# миром для портфеля). Прогон 2026-07-02 на тех же данных стоял в п.п.-шкале
# (SBER -12.0) и давал экономически осмысленный порядок D > C > B > A.
# Гард ниже ловит обе стороны ошибки — заниженную и завышенную шкалу.
POLITICAL_FACTORS = ("sanctions", "geopol")


# Нижний порог применяется ПОКАЗНО и только к долевым инструментам: у акции или
# широкого фонда |β| < 1 п.п. на ПОЛНЫЙ сдвиг фактора невозможен (самый слабый
# класс экспозиции — 5 п.п.), поэтому такое значение почти наверняка долевая
# запись. У облигаций политическая бета законно дробная
# (β = −duration × Δspread_бп/100, см. references/bonds-sensitivity.md §4) —
# к ним нижний порог НЕ применяется.
POLITICAL_BETA_MIN_PLAUSIBLE = 1.0


# |β| выше порога у любой бумаги → шкала завышена (напр. долевую домножили дважды).
POLITICAL_BETA_MAX_PLAUSIBLE = 200.0


# Отдельный потолок для ДОЛГОВОГО класса — зеркало нижнего порога долевого.
# β облигации выводится формулой −duration × Δspread_бп/100 (bonds-sensitivity.md §4).
# Верхняя граница: самая длинная бумага портфеля (дюрация ~15) × самый широкий
# Δspread таблицы (Tier 5, 35 б.п.) = 5.25. Значение выше означает, что бету
# облигации механически домножили на 100 вместе с долевыми — ошибка, которую
# нижний порог по построению не видит, а общий потолок 200 пропускает.
POLITICAL_BETA_MAX_BOND = 6.0


# P1-3: бумага с сильной санкционной бетой, но без заданной позиции, считается
# по полной интенсивности в обе стороны — для уже заблокированной бумаги это
# завышает сторону ужесточения, для нетронутой завышает сторону снятия.
POSITION_REQUIRED_BETA = 20.0

#: P2-4: относительная неопределённость беты по фактору — во сколько раз может
#: ошибаться вклад этого фактора в движение цены. ПРОВИЗОРНЫЕ значения: суждение, а не
#: измерение; калибровки по outcome_log нет. Та же конвенция, что у CAL_*-порогов
#: монитора и ASYMMETRY_CAMP_THRESHOLD в FCA.
FACTOR_BETA_UNCERTAINTY = {
    # Эпизод ОДИН (Rusal/En+ 2018→2019) — в этом главный источник неопределённости, а
    # не в разбросе оценок: −33.7% и −43.1% это два ОКНА одного оценщика
    # (CAAR[0;+1] и CAAR[0;+5]), DiD на тех же данных даёт −39.0%.
    "sanctions": 0.60,
    "geopol": 0.60,      # якорь IMF GFSR-2025, не собственный замер
    "cbr_rate": 0.20,    # β = −duration × Δspread/100: дюрация известна, спред нет
    "usdrub": 0.30,      # pass-through экспортной выручки на длинной истории
    "cnyrub": 0.35,      # то же, но ликвидность пары хуже
    "brent": 0.40,
    "xauusd": 0.40,
}

#: Фактор вне таблицы → худшее известное значение, а не 0: молчаливый ноль сузил бы
#: интервал именно там, где о факторе ничего не известно. В продакшне недостижим —
#: normalize_betas приводит набор ровно к CANONICAL_FACTORS; держится как защита
#: контракта и НЕ засчитывается как покрытие.
FACTOR_BETA_UNCERTAINTY_DEFAULT = 0.60

#: Пол полуширины CI — остаточная неопределённость от каналов, которых в факторном
#: разложении нет.
#:
#: Облигации: независимого кредитного фактора в модели нет — кредит входит только
#: через политический канал (`β = −duration × Δspread_bps/100`, bonds-sensitivity.md
#: §4), и магнитуда таблицы Δspread помечена как заниженная (PSS-5). События вне
#: политики — рефинансирование, отраслевой стресс — не моделируются вовсе.
#:
#: Акции: консервативная граница, унаследованная от прежней формулы и не
#: пере-выведенная. Содержательно покрывает дисперсию бумаг, которым обзор НЕ называет
#: катализаторов. Для покрытых обзором бумаг частично дублируется с идио-слоем вьюера
#: (`aggregate_positions`: total.ci = macro + div + idio, линейное сложение границ) —
#: известное задвоение, зафиксировано как ограничение.
#:
#: Опускать — только вместе с появлением независимого кредитного канала.
CI_MIN_HALF_WIDTH_PP = 5.0

#: Легаси-ветка (contributions=None): доля движения, идущая в полуширину.
CI_LEGACY_DELTA_SHARE = 0.4


# Токены класса актива. Нижний порог шкалы применяется ТОЛЬКО при явном долевом
# классе: неузнанная или неоднозначная строка даёт warning, а не молчаливый пропуск
# и не ложный отказ. Голый `fund` неоднозначен (бывает и облигационным) → warning.
#
# Словарь ровно по тому, что существует: продюсер (`portfolio_returns.
# classify_instrument_type`) эмитит stock / bond / fund / other, а SKILL.md §3.6.2
# предписывает уточнять в priors до fund_equity / bond_fund / fund_gold / bond_fx.
# Спекулятивных токенов здесь быть не должно — непокрытый токен не ловится тестами
# и создаёт ложное ощущение полноты.
EQUITY_TOKENS = ("stock", "equity", "gold")


NON_EQUITY_TOKENS = ("bond", "money")


def is_excluded(holding: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Возвращает (исключена_ли, причина). Исключаются:
      - is_blocked: true
      - value_rub <= 0
      - RUB cash на брокерском счёте
    Money-market funds НЕ исключаются (включаются с factor_betas={}).
    """
    if holding.get("is_blocked", False):
        return True, "blocked"
    if (holding.get("value_rub") or 0) <= 0:
        return True, "zero_value"
    asset_type = (holding.get("asset_type") or "").lower()
    ticker = (holding.get("ticker") or "").upper()
    if asset_type == "cash" and ticker in {"RUB", "RUR", ""}:
        return True, "cash_rub"
    return False, None


def is_money_market(ticker: str, asset_type: str) -> bool:
    return ticker.upper() in MONEY_MARKET_TICKERS or "money_market" in (asset_type or "").lower()


def _portfolio_tickers(holdings: list[dict[str, Any]] | None) -> set[str] | None:
    """
    Тикеры, реально попадающие в расчёт. Зеркалит `is_excluded`: заблокированные и
    нулевые позиции в `per_position` не идут, и гард не должен из-за них падать.
    None → фильтра нет (юнит-тесты).
    """
    if holdings is None:
        return None
    out: set[str] = set()
    for h in holdings:
        if not isinstance(h, dict):
            continue
        excluded, _ = is_excluded(h)
        if excluded or h.get("is_blocked", False):
            continue
        t = h.get("ticker")
        if isinstance(t, str) and t.strip():
            # Движок ищет priors.get(ticker) по ТОЧНОМУ ключу в верхнем регистре
            # (compute_per_position). Гард обязан сопоставлять так же: иначе он
            # гейтит прогон бетой, которую движок всё равно не возьмёт.
            out.add(t.strip().upper())
    return out


def _asset_type_of(
    ticker: str, prior: dict[str, Any], holdings_by_ticker: dict[str, dict[str, Any]]
) -> str | None:
    """
    Класс актива: из PRIOR (приоритет) → из снапшота → None.

    Prior приоритетнее намеренно. `asset_type` снапшота грубый — в живых данных это
    ровно три значения (stock / bond / fund), и под `fund` лежат и золотой фонд, и
    ОБЛИГАЦИОННЫЕ (TLCB, SBGB), у которых беты считаются по bonds-sensitivity и
    законно дробные. Аналитик, раскладывающий фонд при заполнении priors, знает
    его начинку — и должен иметь возможность её объявить.
    """
    for src in (prior, holdings_by_ticker.get(ticker.upper())):
        if isinstance(src, dict):
            at = src.get("asset_type")
            if isinstance(at, str) and at.strip():
                return at.strip().lower()
    return None


def _is_equity_like(ticker: str, asset_type: str | None) -> bool | None:
    """True — долевой (порог применим), False — долговой/MM, None — класс неясен."""
    if is_money_market(ticker, asset_type or ""):
        return False
    if asset_type is None:
        return None
    if any(k in asset_type for k in NON_EQUITY_TOKENS):
        return False
    if any(k in asset_type for k in EQUITY_TOKENS):
        return True
    return None


def _fmt_list(items: list[str], limit: int = 8) -> str:
    """Список адресов: показываем limit, но честно говорим, сколько скрыли."""
    shown = sorted(items)[:limit]
    tail = f" … и ещё {len(items) - limit}" if len(items) > limit else ""
    return ", ".join(shown) + tail


def check_priors_structure(
    priors: Any, holdings: list[dict[str, Any]] | None = None
) -> list[str]:
    """
    Форма priors. Выполняется ВСЕГДА, независимо от --political-scale-check:
    флаг гейтит проверку ШКАЛЫ, а не структуры — иначе битый JSON в режиме
    warn/off роняет движок трейсбеком вместо внятного отказа.

    Как и прочие гарды, смотрит только бумаги портфеля: заготовка под тикер,
    которого в снапшоте нет, не должна ронять прогон.
    """
    errors: list[str] = []
    if not isinstance(priors, dict):
        return [f"priors должен быть dict {{тикер: {{...}}}}, получен {type(priors).__name__}"]
    in_portfolio = _portfolio_tickers(holdings)
    for ticker, prior in priors.items():
        if in_portfolio is not None and str(ticker) not in in_portfolio:
            continue
        if not isinstance(prior, dict):
            errors.append(f"{ticker}: запись priors не dict ({type(prior).__name__})")
            continue
        betas = prior.get("factor_betas")
        if betas is None:
            errors.append(f"{ticker}: нет блока factor_betas")
        elif not isinstance(betas, dict):
            errors.append(
                f"{ticker}.factor_betas не dict ({type(betas).__name__}) — "
                f"беты прочитать нельзя"
            )
    return errors


def check_betas_numeric(
    priors: dict[str, Any], holdings: list[dict[str, Any]] | None = None
) -> list[str]:
    """
    Все беты по каноническим факторам — конечные числа. Единственный владелец
    числовой валидации: дублировать её в гарде шкалы нельзя, иначе одна и та же
    проблема предъявляется дважды в двух разных формах адреса.
    """
    errors: list[str] = []
    in_portfolio = _portfolio_tickers(holdings)
    for ticker, prior in (priors or {}).items():
        if in_portfolio is not None and str(ticker) not in in_portfolio:
            continue
        if not isinstance(prior, dict):
            continue
        betas = prior.get("factor_betas")
        if not isinstance(betas, dict):
            continue
        if is_money_market(str(ticker), str(prior.get("asset_type") or "")):
            continue          # priors MM движок не читает — betas_for_money_market()
        for f in CANONICAL_FACTORS:
            v = betas.get(f)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors.append(f"{ticker}.factor_betas.{f} = {v!r} — не число")
            elif not math.isfinite(float(v)):
                errors.append(f"{ticker}.factor_betas.{f} = {v} — не конечное число")
    return errors


def check_political_beta_scale(
    priors: dict[str, Any], holdings: list[dict[str, Any]] | None = None
) -> tuple[list[str], list[str]]:
    """
    Проверка ШКАЛЫ политических бет (P0-1). Возвращает (errors, warnings).
    Числовую валидность и форму проверяют check_betas_numeric / check_priors_structure.

    Проверка ПОКАЗНАЯ: частичная миграция («домножили банки, забыли экспортёров») —
    самый вероятный сценарий ошибки, и одна верная запись не должна разоружать
    проверку для остальных. Нижний порог применяется только при ЯВНО долевом
    классе актива; неоднозначный класс (голый `fund`) и незнакомая строка дают
    warning, а не отказ и не молчание.
    """
    errors: list[str] = []
    warns: list[str] = []
    if not isinstance(priors, dict):
        return errors, warns
    by_ticker = {
        str(h.get("ticker") or "").upper(): h
        for h in (holdings or [])
        if isinstance(h, dict)
    }
    in_portfolio = _portfolio_tickers(holdings)

    low: list[str] = []
    high: list[str] = []
    bond_high: list[str] = []
    unknown_class: list[str] = []
    no_political: list[str] = []
    nonzero_seen = False
    checked_records = 0

    for ticker, prior in priors.items():
        tkr = str(ticker)
        if in_portfolio is not None and tkr not in in_portfolio:
            continue
        if not isinstance(prior, dict):
            continue
        betas = prior.get("factor_betas")
        if not isinstance(betas, dict):
            continue
        at = _asset_type_of(tkr, prior, by_ticker)
        equity = _is_equity_like(tkr, at)
        if is_money_market(tkr, at or ""):
            continue
        checked_records += 1
        present = [f for f in POLITICAL_FACTORS if betas.get(f) is not None]
        if not present:
            no_political.append(tkr)
            continue
        for f in present:
            v = betas.get(f)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue          # владелец проверки — check_betas_numeric
            fv = float(v)
            if not math.isfinite(fv) or fv == 0.0:
                continue
            nonzero_seen = True
            if abs(fv) > POLITICAL_BETA_MAX_PLAUSIBLE:
                high.append(f"{tkr}.{f}={fv:g}")
            elif equity is False and abs(fv) > POLITICAL_BETA_MAX_BOND:
                bond_high.append(f"{tkr}.{f}={fv:g}")
            elif abs(fv) < POLITICAL_BETA_MIN_PLAUSIBLE:
                if equity is True:
                    low.append(f"{tkr}.{f}={fv:g}")
                elif equity is None and tkr not in unknown_class:
                    unknown_class.append(tkr)

    if low:
        errors.append(
            f"ШКАЛА ПОЛИТИЧЕСКИХ БЕТ: {len(low)} бет(ы) долевых бумаг с |β| < "
            f"{POLITICAL_BETA_MIN_PLAUSIBLE:g} — это долевая запись, умножь ИХ на 100. "
            f"Контракт: β — п.п. цены на 1.0 единицы интенсивности (банки ≈ -35, "
            f"не -0.35). {_fmt_list(low)}. "
            f"См. references/sector-sensitivities.md «Контракт единиц»."
        )
    if high:
        errors.append(
            f"ШКАЛА ПОЛИТИЧЕСКИХ БЕТ: |β| > {POLITICAL_BETA_MAX_PLAUSIBLE:g} у "
            f"{len(high)} бет(ы) — полный сдвиг фактора двигал бы бумагу больше "
            f"чем на 200%. {_fmt_list(high)}"
        )
    if bond_high:
        errors.append(
            f"ШКАЛА ПОЛИТИЧЕСКИХ БЕТ: у {len(bond_high)} долговых бумаг |β| > "
            f"{POLITICAL_BETA_MAX_BOND:g}. У облигации β = −duration × Δspread_бп/100 "
            f"и не превышает ~5 даже у самой длинной: похоже, беты домножили на 100 "
            f"вместе с долевыми. Пересчитай по формуле, а не масштабированием. "
            f"{_fmt_list(bond_high)}. См. references/bonds-sensitivity.md §4."
        )
    if unknown_class:
        warns.append(
            f"Класс актива неоднозначен у {len(unknown_class)} бумаг(и) с дробной "
            f"политической бетой — проверка шкалы по ним ПРОПУЩЕНА: "
            f"{_fmt_list(unknown_class)}. Голый `fund` бывает и облигационным; "
            f"уточни asset_type в priors (`fund_equity` / `bond_fund` / `fund_gold`)."
        )
    if checked_records and not nonzero_seen and not errors:
        warns.append(
            f"Политический канал полностью нулевой: ни одной ненулевой беты по "
            f"sanctions/geopol среди {checked_records} проверенных бумаг. Сценарные "
            f"дилы санкций и геополитики не влияют на результат — это осознанно?"
        )
    if no_political:
        warns.append(
            f"Политических бет нет вовсе у {len(no_political)} бумаг(и): "
            f"{_fmt_list(no_political)}. Санкционные дилы их не двигают — "
            f"проверь, что ключи не потерялись при переносе."
        )
    return errors, warns


def check_sanctions_positions(
    priors: dict[str, Any], holdings: list[dict[str, Any]] | None = None
) -> tuple[list[str], list[str]]:
    """
    Валидация `sanctions_position` (P1-3). Возвращает (errors, warnings).
      • нечисловое значение → error (тихо игнорировать поле нельзя: расчёт
        молча уедет на полную интенсивность);
      • значение вне [0,1] → error (шкала определена только на отрезке);
      • сильная санкционная бета без позиции → warning с перечислением бумаг.
    """
    errors: list[str] = []
    missing: list[str] = []
    in_portfolio = _portfolio_tickers(holdings)
    for ticker, prior in (priors or {}).items():
        if in_portfolio is not None and str(ticker) not in in_portfolio:
            continue
        if not isinstance(prior, dict):
            continue
        if is_money_market(str(ticker), str(prior.get("asset_type") or "")):
            continue          # priors MM движок не читает
        raw = prior.get("sanctions_position")
        betas = prior.get("factor_betas") or {}
        beta_s = betas.get("sanctions") if isinstance(betas, dict) else None
        if raw is None:
            try:
                if beta_s is not None and abs(float(beta_s)) >= POSITION_REQUIRED_BETA:
                    missing.append(str(ticker))
            except (TypeError, ValueError):
                pass
            continue
        if isinstance(raw, bool):
            errors.append(f"{ticker}.sanctions_position = {raw!r} — не число")
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{ticker}.sanctions_position = {raw!r} — не число")
            continue
        if not math.isfinite(val) or not 0.0 <= val <= 1.0:
            errors.append(
                f"{ticker}.sanctions_position = {val:g} вне [0,1]: 0 — бумага не "
                f"тронута санкциями, 1 — максимально заблокирована"
            )
    warnings_: list[str] = []
    if missing:
        warnings_.append(
            f"sanctions_position не задан у {len(missing)} бумаг(и) с |β_sanctions| ≥ "
            f"{POSITION_REQUIRED_BETA:g}: {_fmt_list(missing)}. "
            f"Считаются по полной интенсивности в обе стороны — для уже "
            f"заблокированной бумаги это завышает ужесточение, для нетронутой — снятие."
        )
    return errors, warnings_


def check_political_horizon_path(scenarios: dict[str, Any]) -> list[str]:
    """
    Гард горизонт-инвариантности (P0-2). Политический дил, одинаковый на всех
    горизонтах, означает «разрядка через полгода = разрядка через два года».
    Warning-only: на одногоризонтном прогоне это норма.
    """
    warns: list[str] = []
    for sid, sc in (scenarios or {}).items():
        if not isinstance(sc, dict):
            warns.append(f"{sid}: сценарий не dict — гард горизонтного пути пропущен")
            continue
        fbh = sc.get("factors_by_horizon")
        if not isinstance(fbh, dict) or len(fbh) < 2:
            continue
        for f in POLITICAL_FACTORS:
            vals = []
            for hk, factors in fbh.items():
                if isinstance(factors, dict) and factors.get(f) is not None:
                    try:
                        vals.append((hk, float(factors[f])))
                    except (TypeError, ValueError):
                        pass
            if len(vals) < 2:
                continue
            uniq = {round(v, 6) for _, v in vals}
            if len(uniq) == 1 and next(iter(uniq)) != 0.0:
                hks = "/".join(hk for hk, _ in vals)
                warns.append(
                    f"{sid}.{f} = {vals[0][1]:g} одинаков на {hks} — интенсивность не "
                    f"растёт с горизонтом. Убедись, что так и задумано, а не скаляр "
                    f"скопирован на все горизонты (P0-2)."
                )
    return warns


def check_scenario_weights(
    scenarios: dict[str, Any], horizon_keys: list[str]
) -> tuple[list[str], list[str]]:
    """
    Валидация весов сценариев (errors, warnings).

    Веса по горизонтам обязаны покрывать все сценарии и суммироваться в 1 на
    КАЖДОМ горизонте: частично заполненный блок молча смешал бы веса разных
    убеждений. Скаляры проверяются мягко — Pure Shell по построению даёт 0.25×4,
    и отклонение от единицы там осмысленно только как предупреждение.
    """
    errors: list[str] = []
    warns: list[str] = []
    if not isinstance(scenarios, dict) or not scenarios:
        return ["scenarios пуст — считать нечего"], warns
    sids = [s for s in scenarios]
    has_pbh = [s for s in sids
               if isinstance(scenarios.get(s), dict)
               and isinstance(scenarios[s].get("p_by_horizon"), dict)]
    if has_pbh:
        missing = [s for s in sids if s not in has_pbh]
        if missing:
            errors.append(
                f"p_by_horizon задан у {sorted(has_pbh)}, но не у {sorted(missing)} — "
                f"смешивать веса по горизонтам со скалярными нельзя"
            )
        # После PSS-9 горизонтные веса читают все потребители total-return: ценовой
        # слой, bond carry, portfolio-integrated-view (включая идио-слой и MC),
        # вьюер и coherence-audit. Скаляр `p` при этом остаётся ОБЯЗАТЕЛЬНЫМ, и это
        # не рудимент: по нему считается диагностика нормировки (сумма весов и её
        # severity), и он же — деградация на горизонтах, которых в блоке нет
        # (`_p_norm`/`_scenario_p_norm` падают на скаляр, а не на ноль).
        # Исключение одно: macro-forecast-chain --mode RECALIBRATE горизонтных весов
        # не поддерживает и честно отказывается их обрабатывать (MFC-5).
        no_scalar = [s for s in has_pbh
                     if not isinstance(scenarios[s].get("p",
                                       scenarios[s].get("probability")), (int, float))
                     or isinstance(scenarios[s].get("p",
                                   scenarios[s].get("probability")), bool)]
        if no_scalar:
            errors.append(
                f"p_by_horizon без скалярного `p` у {sorted(no_scalar)}: скаляр "
                f"остаётся обязательным — по нему считается диагностика нормировки "
                f"и он служит деградацией на горизонтах, которых нет в блоке. "
                f"Задай `p` рядом."
            )
        else:
            warns.append(
                "Веса по горизонтам применяются к ценовому слою, bond carry и "
                "portfolio-integrated-view (PSS-9). Не поддерживает их только "
                "macro-forecast-chain --mode RECALIBRATE — он на таких матрицах "
                "отказывается работать (MFC-5), пересчёт Layer 2 marginal придётся "
                "делать иначе."
            )
        for hk in horizon_keys:
            vals = {}
            for s in has_pbh:
                v = scenarios[s]["p_by_horizon"].get(hk)
                if not isinstance(v, (int, float)) or isinstance(v, bool) \
                        or not math.isfinite(float(v)):
                    errors.append(f"{s}.p_by_horizon.{hk} = {v!r} — не число")
                elif not 0.0 <= float(v) <= 1.0:
                    errors.append(f"{s}.p_by_horizon.{hk} = {float(v):g} вне [0,1]")
                else:
                    vals[s] = float(v)
            if len(vals) == len(sids):
                total = sum(vals.values())
                if abs(total - 1.0) > 1e-6:
                    errors.append(
                        f"p_by_horizon на {hk}: сумма весов {total:.6f} != 1 "
                        f"({ {k: round(v, 4) for k, v in vals.items()} })"
                    )
        return errors, warns
    scal: dict[str, float] = {}
    broken: list[str] = []
    for s in sids:
        sc = scenarios.get(s)
        if not isinstance(sc, dict):
            broken.append(f"{s}: сценарий не dict")
            continue
        v = sc.get("p")
        if v is None:
            v = sc.get("probability")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            # Молча взять 0.0 нельзя: сценарий выпадет из ожидания, а числа
            # останутся правдоподобными. None в `p` тоже сюда — `.get` с дефолтом
            # его не перехватывает.
            broken.append(f"{s}.p = {v!r} — вес не задан числом")
        elif not math.isfinite(float(v)):
            broken.append(f"{s}.p = {v} — не конечное число")
        else:
            scal[s] = float(v)
    if broken:
        errors.extend(broken)
        return errors, warns
    total = sum(scal.values())
    if abs(total - 1.0) > 1e-3:
        warns.append(
            f"Сумма вероятностей сценариев {total:.4f} != 1 — проверь матрицу"
        )
    return errors, warns


def compute_base_value_rub(snapshot: dict[str, Any]) -> float:
    """
    Знаменатель ВСЕХ pct-полей контракта баз расчёта (`base_value_rub`,
    docs/investment/task-stress-basis-contract.md §1.1): Σ `value_rub`
    неблокированных holdings + `cash.total_rub`.

    Единственный источник этой суммы — считать её в двух местах (bond carry
    portfolio-level, price-only aggregator) отдельно означало бы воспроизвести
    тот же класс дрейфа, ради устранения которого пишется контракт, только на
    уровне знаменателя, а не имени поля. Отличается от `is_excluded`
    (используется для отбора `per_position`): та функция ещё и выбрасывает
    RUB cash со счёта — здесь кэш, наоборот, обязателен (см. `base_value_note`
    §1.1: «holdings unblocked + кэш»).
    """
    holdings = snapshot.get("holdings") or []
    total = sum(
        float(h.get("value_rub") or 0)
        for h in holdings
        if isinstance(h, dict) and not h.get("is_blocked", False)
    )
    total += float((snapshot.get("cash") or {}).get("total_rub") or 0)
    return total


def compute_positions_value_rub(snapshot: dict[str, Any]) -> float:
    """
    БЕЗ кэша — Σ `value_rub` неблокированных holdings. Это ТОТ ЖЕ знаменатель,
    что `compute_per_position.compute_total_value` использует для самого
    `weight_pct` (`weight_pct = value_rub / total_value * 100`, БЕЗ кэша) —
    здесь продублирован намеренно (одна строка, риск расхождения нулевой), а
    не импортирован, потому что `compute_per_position.py` — единственный
    файл скилла с sibling-импортом В ОБРАТНУЮ сторону (импортирует ИЗ
    `input_contract`, не наоборот, PSS-7).

    ЗАЧЕМ ОТДЕЛЬНО ОТ `compute_base_value_rub`. `weight_pct` архивных и живых
    per_position нормирован на эту, БЕЗ-кэшевую, базу (подтверждено кодом
    compute_per_position.py и комментарием `weight_base_note` в архиве:
    «weight_pct нормирован на non-cash unblocked holdings, Σ = 100.0»).
    `base_value_rub` контракта (2026-09-18) — знаменатель ПРОЦЕНТОВ, он
    ВКЛЮЧАЕТ кэш по определению задачи (§1.1). Если при развороте
    `weight_pct → ₽` домножить на `base_value_rub` вместо этой функции,
    сумма систематически завышается на долю кэша (в портфеле с cash_rub_pct
    ~1% — систематическая ошибка ~1% суммы, что уже превышает допуск ±0.5%
    RECONCILE 3.7). Обнаружено 2026-09-18 при построении нормализатора
    архива — синтетические тесты задачи 2 с нулевым кэшем этот класс ошибки
    не ловили.
    """
    holdings = snapshot.get("holdings") or []
    return sum(
        float(h.get("value_rub") or 0)
        for h in holdings
        if isinstance(h, dict) and not h.get("is_blocked", False)
    )
