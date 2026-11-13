#!/usr/bin/env python3
"""
recalibrate.py

RECALIBRATE-mode для macro-forecast-chain (D7).
Lazy weight update: читает новые веса из scenario YAML (SSOT),
пересчитывает Layer 2 marginals, обновляет modal/hedge ranking.
Никаких LLM-вызовов. Время выполнения < 30 секунд.

CLI:
    python3 recalibrate.py \\
        --scenario scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml \\
        [--forecasts-dir Claude-Memory/forecasts/] \\
        [--stress Claude-Memory/macro-chain/macro-scenarios-2026-05-04.yaml] \\
        [--output macro-scenarios-updated.yaml] \\
        [--strict] [--pretty]

НЕ запускает FCA. НЕ пересчитывает Layer 1 marginal. НЕ меняет conditional values.
Только labels + Layer 2 marginal + modal/hedge ranking.

Зависимости: PyYAML (уже используется в migrate_to_conditional.py).
"""
from __future__ import annotations

import argparse
import json
import copy
import io
import math
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Общий модуль: сначала каталог скрипта (пакет .skill), затем _shared-references/ репозитория.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import scenario_weights as _sw  # noqa: E402

try:  # опционально: точечная правка с сохранением комментариев и формата
    from ruamel.yaml import YAML as _RuamelYAML
except ImportError:  # pragma: no cover - зависит от окружения
    _RuamelYAML = None

#: Текст предупреждения, когда ruamel.yaml недоступен и файлы переписаны целиком.
NO_RUAMEL_WARNING = ("ruamel.yaml не установлен — файлы переписаны с потерей "
                     "комментариев и формата")

STALE_THRESHOLD = 0.01  # расхождение Layer 2 > 1% → stale
REQUIRED_SCENARIOS = {"A", "B", "C", "D"}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StaleMarginal:
    forecast_file: str
    horizon: str
    old_value: float
    new_value: float
    divergence_pct: float


@dataclass
class RecalibrateResult:
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    modal_changed: bool
    old_modal: str | None
    new_modal: str | None
    coverage_warning: str | None
    stale_recalculated: list[StaleMarginal]
    updated_files: list[str]
    #: Что НЕ тронуто и почему. Причины: не `active` (архив — superseded/expired),
    #: чужая матрица (`source_matrix`), непересчитываемый метод, неоднозначный
    #: модальный сценарий. Тихий пропуск неотличим от «пересчитали всё» — ровно
    #: тот дефект, из-за которого режим годами не читал ни одной живой матрицы и
    #: это не всплывало.
    skipped_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Нефатальные предупреждения прогона (напр. запись без ruamel.yaml).
    warnings: list[str] = field(default_factory=list)
    #: Откуда веса: `site` (файл сайта) | `matrix` (scenario_triggers матрицы).
    weights_source: str = "matrix"
    #: Мета источника весов: для `site` — файл, set_at, сроки, способы получения дат; для `matrix` — имя файла.
    weights_meta: dict = field(default_factory=dict)


class StaleMarginalError(Exception):
    def __init__(self, stale: list[StaleMarginal]) -> None:
        self.stale = stale
        lines = "\n".join(
            f"  {s.forecast_file} [{s.horizon}]: "
            f"{s.old_value:.4f} → {s.new_value:.4f} ({s.divergence_pct:.1f}%)"
            for s in stale
        )
        super().__init__(
            f"{len(stale)} stale marginal(s) detected (--strict mode).\n"
            "Инструкция: пересмотрите прогнозы вручную или запустите без --strict.\n"
            f"Stale forecasts:\n{lines}"
        )


class WeightValidationError(Exception):
    pass


class HorizonOutsideMatrix(Exception):
    """Горизонт(ы) прогноза без весов в p_by_horizon — файл не пересчитывается."""

    def __init__(self, horizons: list[str]) -> None:
        self.horizons = horizons
        super().__init__(
            f"горизонты {horizons} вне дат матрицы — весов на них нет, "
            f"интерполяция запрещена (weights_by_horizon: убеждение на срок — "
            f"суждение); файл пропущен целиком"
        )


# ---------------------------------------------------------------------------
# Weight helpers
# ---------------------------------------------------------------------------

def _find_triggers(doc: Any) -> Any:
    """
    `scenario_triggers` в двух местах: спека (`scenario-yaml-spec.md` §1.1) кладёт
    блок под `matrix`, все шесть живых матриц — на верхний уровень. Читаем оба,
    верхний уровень приоритетнее (там реальность). Зеркало
    `build_stress_stub.py:133`.
    """
    if not isinstance(doc, dict):
        return None
    top = doc.get("scenario_triggers")
    if top is not None:
        return top
    matrix = doc.get("matrix")
    if isinstance(matrix, dict):
        return matrix.get("scenario_triggers")
    return None


def load_weights(path: Path) -> dict[str, float]:
    """
    Читает SSOT scenario YAML, возвращает {A: p, B: p, C: p, D: p}.

    MFC-5 (2026-08-05): разбор через `yaml.safe_load`. Прежний построчный regex
    ждал mapping-форму `A:` → `probability:` с конкретными отступами и на ВСЕХ
    шести живых матрицах возвращал `{}` — веса в них лежат списком
    (`- scenario_id: A` / `probability: 0.25`). Пустой словарь дальше
    останавливался валидатором суммы, так что тихого неверного пересчёта не
    было, но и работать режим не мог ни на одном реальном файле.

    Форма блока — только СПИСОК элементов со `scenario_id` (спека §1.1 и все
    живые файлы). Отсутствие блока или чужая форма — явный отказ, а не пустой
    словарь: тихое `{}` и было тем дефектом, который здесь чинится.

    Матрицы с `p_by_horizon` (MFC-5 шаг 2, 2026-08-06): скаляр остаётся
    обязательным рядом с блоком (контракт PSS-9) и возвращается отсюда как
    раньше; горизонтные веса читает `load_horizon_weights`, и Layer 2
    агрегируется весами СВОЕГО горизонта. Прежний отказ на `p_by_horizon` снят.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SystemExit(f"ERROR: {path} не разбирается как YAML: {e}") from e

    triggers = _find_triggers(doc)
    if triggers is None:
        raise SystemExit(
            f"ERROR: {path} — не найден `scenario_triggers` ни на верхнем уровне, "
            f"ни в `matrix`. Веса сценариев живут только там "
            f"(scenario-yaml-spec.md §1.1)."
        )
    if not isinstance(triggers, list):
        raise SystemExit(
            f"ERROR: {path} — `scenario_triggers` имеет тип "
            f"{type(triggers).__name__}, ожидается список элементов со "
            f"`scenario_id` (scenario-yaml-spec.md §1.1)."
        )
    items = [t for t in triggers if isinstance(t, dict)]

    weights: dict[str, float] = {}
    for t in items:
        sid = t.get("scenario_id")
        p = t.get("probability")
        if not isinstance(sid, str) or isinstance(p, bool) or not isinstance(p, (int, float)):
            continue
        weights[sid.strip()] = float(p)
    return weights


def load_horizon_weights(path: Path) -> dict[str, dict[str, float]] | None:
    """
    MFC-5 шаг 2: веса по горизонтам из `p_by_horizon`, ключованные ДАТАМИ.

    Возвращает {дата-ISO: {sid: p}} либо None, если блока нет ни у одного
    сценария (скалярный режим, поведение до шага 2 бит-в-бит).

    Ключи `p_by_horizon` — hNN; в даты они переводятся по самой матрице:
    `matrix.horizon_intermediate` (по возрастанию) + `matrix.horizon` — ровно
    те даты, которыми ключуется `marginal.values` прогнозов. Порядковое
    сопоставление: i-й горизонт (по возрастанию NN) ↔ i-я дата. Прогоны
    прогнозов с датами вне этого набора (h18-файлы: `2027-12-31`) весов не
    имеют — интерполяция запрещена сознательно, такие файлы пропускаются
    целиком в `recalibrate()`.

    Дефекты формы — явный отказ, а не тихая деградация на скаляр (подменить
    убеждение молча — ровно то, от чего защищал прежний полный отказ):
      - блок у ЧАСТИ сценариев;
      - разные наборы горизонтных ключей у разных сценариев;
      - ключ не вида hNN;
      - число дат матрицы ≠ числу горизонтных ключей;
      - сумма весов ≠ 1 на любом горизонте (WeightValidationError).
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SystemExit(f"ERROR: {path} не разбирается как YAML: {e}") from e

    triggers = _find_triggers(doc)
    items = [t for t in (triggers or []) if isinstance(t, dict)]
    with_block = [t for t in items if isinstance(t.get("p_by_horizon"), dict)]
    if not with_block:
        return None
    if len(with_block) != len(items):
        missing = sorted(str(t.get("scenario_id")) for t in items
                         if not isinstance(t.get("p_by_horizon"), dict))
        raise SystemExit(
            f"ERROR: {path} — p_by_horizon задан у части сценариев "
            f"(нет у {missing}). Частичный блок неоднозначен: либо у всех, "
            f"либо ни у кого."
        )

    key_sets = {frozenset(t["p_by_horizon"].keys()) for t in with_block}
    if len(key_sets) != 1:
        raise SystemExit(
            f"ERROR: {path} — сценарии несут РАЗНЫЕ наборы горизонтов в "
            f"p_by_horizon: {sorted(map(sorted, key_sets))}."
        )
    hks = list(next(iter(key_sets)))
    try:
        hks.sort(key=lambda k: int(re.fullmatch(r"h(\d+)", str(k)).group(1)))
    except AttributeError:
        raise SystemExit(
            f"ERROR: {path} — ключ p_by_horizon не вида hNN: {sorted(map(str, hks))}."
        ) from None

    matrix = doc.get("matrix") if isinstance(doc.get("matrix"), dict) else {}
    inter = matrix.get("horizon_intermediate") or []
    final = matrix.get("horizon")
    dates: list[str] = []
    for d in list(inter) + ([final] if final is not None else []):
        dates.append(d.isoformat() if hasattr(d, "isoformat") else str(d))
    dates.sort()
    if len(dates) != len(hks):
        raise SystemExit(
            f"ERROR: {path} — {len(hks)} горизонтов в p_by_horizon "
            f"({hks}) против {len(dates)} дат матрицы "
            f"(horizon_intermediate + horizon = {dates}): порядковое "
            f"сопоставление горизонт↔дата невозможно."
        )

    out: dict[str, dict[str, float]] = {}
    for hk, dt in zip(hks, dates):
        w: dict[str, float] = {}
        for t in with_block:
            sid = t.get("scenario_id")
            p = t["p_by_horizon"].get(hk)
            if not isinstance(sid, str) or isinstance(p, bool) \
                    or not isinstance(p, (int, float)):
                continue
            w[sid.strip()] = float(p)
        try:
            validate_weights(w)
        except WeightValidationError as e:
            raise WeightValidationError(f"p_by_horizon[{hk} → {dt}]: {e}") from e
        out[dt] = w
    return out


def horizon_label_dates(path: Path) -> dict[str, str]:
    """{hNN: дата-ISO} по соответствию матрицы (порядковое, как в `load_horizon_weights`); {} без p_by_horizon."""
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    items = [t for t in (_find_triggers(doc) or []) if isinstance(t, dict)]
    blocks = [t["p_by_horizon"] for t in items if isinstance(t.get("p_by_horizon"), dict)]
    if not blocks:
        return {}
    hks = sorted(blocks[0], key=lambda k: int(re.fullmatch(r"h(\d+)", str(k)).group(1)))
    matrix = doc.get("matrix") if isinstance(doc.get("matrix"), dict) else {}
    dates = [d.isoformat() if hasattr(d, "isoformat") else str(d)
             for d in list(matrix.get("horizon_intermediate") or [])
             + ([matrix["horizon"]] if matrix.get("horizon") is not None else [])]
    dates.sort()
    return dict(zip(hks, dates))


def _matrix_h12_date(path: Path) -> str:
    """Дата, которую матрица называет h12; без p_by_horizon — matrix.date + 12 месяцев."""
    labels = horizon_label_dates(path)
    if "h12" in labels:
        return labels["h12"]
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    md = (doc.get("matrix") or {}).get("date") if isinstance(doc, dict) else None
    if md is None:
        raise SiteWeightsRefused(f"{path.name}: нет matrix.date — не из чего получить дату h12 для скаляра")
    if not hasattr(md, "isoformat"):
        from datetime import date as _d
        md = _d.fromisoformat(str(md))
    try:
        return md.replace(year=md.year + 1).isoformat()
    except ValueError:  # 29 февраля
        return md.replace(year=md.year + 1, day=28).isoformat()


class SiteWeightsRefused(Exception):
    """Файл сайта есть, но использовать его нельзя (битый или чужой набор сценариев)."""


def _forecast_dates(forecasts_dir: Path | None, scenario_yaml_path: Path) -> list[str]:
    """Все даты-горизонты Layer 2 пересчитываемых прогнозов (active, наша матрица)."""
    out: set[str] = set()
    if forecasts_dir is None or not forecasts_dir.exists():
        return []
    for fp in sorted(forecasts_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8"))
            if not data or not has_conditional_block(data):
                continue
            if str(data.get("status") or "").strip().lower() != "active":
                continue
            if matrix_matches(data, scenario_yaml_path) is not None:
                continue
            for sc in (data["conditional_on_scenarios"].get("by_scenario") or {}).values():
                out.update(_iter_horizons((sc or {}).get("values") or {}))
        except Exception:  # noqa: BLE001 - файл с ошибкой отдаст её в основном проходе
            continue
    return sorted(out)


def resolve_site_weights(scenario_yaml_path: Path, matrix_weights: dict[str, float],
                         forecasts_dir: Path | None, site_path: Path | None,
                         use_site: bool = True):
    """(скаляр, weights_by_date, мета) из файла сайта либо None, если его нет/отключён.
    Файл есть, но не годен → SiteWeightsRefused."""
    if not use_site:
        return None
    path = site_path if site_path is not None else _sw.site_file_for(scenario_yaml_path)
    try:
        site = _sw.load_site(path)
    except _sw.SiteWeightsError as e:
        raise SiteWeightsRefused(f"файл весов сайта не годится: {e}") from e
    if site is None:
        if site_path is not None:
            raise SiteWeightsRefused(f"файл весов сайта {path} не найден")
        return None
    site_ids = set(next(iter(site["weights"].values())))
    if site_ids != set(matrix_weights):
        raise SiteWeightsRefused(
            f"{path.name}: сценарии файла сайта {sorted(site_ids)} не совпадают со сценариями "
            f"матрицы {sorted(matrix_weights)}")
    h12 = _matrix_h12_date(scenario_yaml_path)
    dates = sorted(set(_forecast_dates(forecasts_dir, scenario_yaml_path)) | {h12})
    try:
        by_date, meta = _sw.weights_on_dates(site, dates)
    except _sw.SiteWeightsError as e:
        raise SiteWeightsRefused(f"{path.name}: {e}") from e
    meta["scalar_date"] = h12
    return by_date[h12], by_date, meta


def validate_weights(weights: dict[str, float]) -> None:
    """Проверяет: все 4 сценария присутствуют + сумма ≈ 1.0 ± 0.001."""
    missing = REQUIRED_SCENARIOS - set(weights)
    if missing:
        raise WeightValidationError(
            f"Отсутствуют сценарии: {sorted(missing)}. "
            f"Найдены: {sorted(weights)}"
        )
    # NaN обязан отвергаться ЯВНО: `nan > 0.001` в Python — False, поэтому
    # проверка суммы ниже его молча пропускала. Достижимо стало после перехода
    # на yaml.safe_load (MFC-5): PyYAML разбирает `.nan` в float('nan'), а
    # прежний построчный regex требовал цифру и такого значения не видел.
    # Последствия были бы тихими: `.nan` уезжает в Layer 2 marginal на диск, а
    # modal_scenario() возвращает первый ключ (все сравнения с NaN — False).
    bad = [sid for sid, v in weights.items() if not math.isfinite(float(v))]
    if bad:
        raise WeightValidationError(
            f"Нечисловые веса (NaN/inf) у {sorted(bad)}: {weights}"
        )
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        raise WeightValidationError(
            f"Сумма весов {total:.6f} ≠ 1.0 (допуск ±0.001). Веса: {weights}"
        )


def modal_scenario(weights: dict[str, float]) -> str:
    """Возвращает ID сценария с максимальным весом."""
    return max(weights, key=lambda k: weights[k])


def hedge_target(weights: dict[str, float]) -> str:
    """Возвращает ID сценария с минимальным весом."""
    return min(weights, key=lambda k: weights[k])


# ---------------------------------------------------------------------------
# Marginal computation (inline, без импорта из других скиллов)
# ---------------------------------------------------------------------------

def aggregate_marginal_simple(
    by_scenario: dict,
    weights: dict[str, float],
    horizon: str,
    method: str = "linear",
    modal_scenario_id: str | None = None,
) -> float | None:
    """
    Пересчёт Layer 2 marginal central для одного горизонта.
    Поддерживает: linear, modal, nonlinear.
    axis_dependent — не поддерживается в RECALIBRATE (требует контекст оси).
    """
    try:
        if method == "linear":
            return sum(
                weights[sid] * _get_central(by_scenario[sid]["values"], horizon)
                for sid in ["A", "B", "C", "D"]
            )
        elif method in ("modal", "nonlinear"):
            # Ветка требует ОДНОЗНАЧНОГО модального сценария. Источник первой
            # очереди — сам прогноз (`marginal.modal_scenario_id`). Если он не
            # назван, берётся единственный лидер по весам; при равных весах
            # (Pure Shell D1 — 0.25×4, ровно то, что стоит во всех живых
            # матрицах) `max()` вернул бы ПЕРВЫЙ ключ словаря, и значение
            # прогноза определял бы порядок ключей в YAML. Тогда — отказ (None,
            # горизонт пропускается), а не выбор наугад.
            sid = modal_scenario_id if modal_scenario_id in by_scenario else None
            if sid is None:
                top = max(weights.values())
                leaders = [s for s, w in weights.items() if abs(w - top) < 1e-12]
                if len(leaders) != 1:
                    return None
                sid = leaders[0]
            return float(_get_central(by_scenario[sid]["values"], horizon))
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None


def matrix_matches(data: dict, scenario_yaml_path: Path) -> str | None:
    """
    Спека §1.3: пересчитываются ТОЛЬКО прогнозы, чей `source_matrix` указывает на
    ЭТУ матрицу. Возвращает причину пропуска или None, если файл наш.

    Без фильтра прогон по `--forecasts-dir` переписывал Layer 2 у прогнозов,
    привязанных к ДРУГИМ матрицам: в живой библиотеке лежат файлы с
    `source_matrix` от 05-04, 06-10 и 07-01 одновременно, и запуск с матрицей
    07-01 трогал все. До 2026-08-05 это не проявлялось только потому, что
    `load_weights` не читала ни одной живой матрицы и режим падал раньше.

    Сравнение по имени файла: в артефактах путь записан относительно
    Claude-Memory (`scenarios/…yaml`), на вход приходит абсолютный.
    """
    src = (data.get("conditional_on_scenarios") or {}).get("source_matrix")
    if not src:
        return "нет source_matrix"
    if Path(str(src)).name != scenario_yaml_path.name:
        return f"source_matrix → {Path(str(src)).name}"
    return None


def _get_central(values_dict: dict, horizon: str) -> float:
    """Ищет ключ horizon в values_dict с нормализацией date-объектов → строку."""
    entry = _lookup_horizon(values_dict, horizon)
    if entry is None:
        raise KeyError(f"horizon {horizon!r} not found")
    return float(entry["central"])


def _lookup_horizon(d: dict, horizon: str) -> dict | None:
    """Поиск с нормализацией ключей (yaml может разобрать дату как date-объект)."""
    if horizon in d:
        return d[horizon]
    for k, v in d.items():
        if hasattr(k, "isoformat") and k.isoformat() == horizon:
            return v
    return None


def _iter_horizons(values_dict: dict) -> list[str]:
    """Все горизонты из values_dict в виде строк."""
    result = []
    for k in values_dict:
        result.append(k.isoformat() if hasattr(k, "isoformat") else str(k))
    return result


# ---------------------------------------------------------------------------
# Conditional block: detect and recalculate
# ---------------------------------------------------------------------------

def has_conditional_block(data: dict) -> bool:
    return bool(data.get("conditional_on_scenarios"))


def _marginal_snapshot(data: dict) -> dict[str, float | None]:
    """
    Числовой слепок Layer 2 для сравнения «изменилось / не изменилось».

    Сравнение ЧИСЛАМИ, а не текстом: `round()` возвращает float, и после
    пересчёта хранившееся `central: 80` становится `80.0`. Текстовое сравнение
    считало бы это изменением и гоняло бы перезапись файла (а с ней —
    переформатирование всего YAML) на ровном месте.
    """
    values = ((data.get("conditional_on_scenarios") or {}).get("marginal")
              or {}).get("values") or {}
    out: dict[str, float | None] = {}
    for k, v in values.items():
        key = k.isoformat() if hasattr(k, "isoformat") else str(k)
        central = v.get("central") if isinstance(v, dict) else v
        try:
            out[key] = round(float(central), 6)
        except (TypeError, ValueError):
            out[key] = None
    return out


def recalculate_layer2(
    data: dict,
    new_weights: dict[str, float],
    forecast_file: str,
    weights_by_date: dict[str, dict[str, float]] | None = None,
) -> tuple[list[StaleMarginal], dict, list[str]]:
    """
    Пересчитывает Layer 2 marginals в data['conditional_on_scenarios'].
    Возвращает (stale_list, updated_data, skipped_horizons).
    Data изменяется in-place.

    `weights_by_date` (MFC-5 шаг 2) — {дата-ISO: {sid: p}} из p_by_horizon:
    каждый горизонт агрегируется весами СВОЕГО горизонта. Горизонт вне набора
    дат матрицы (h18-файлы) — `HorizonOutsideMatrix`: файл пропускается
    ЦЕЛИКОМ в recalibrate(), частичный пересчёт оставил бы в одном файле
    Layer 2 на двух разных наборах убеждений.

    `skipped_horizons` — горизонты, которые пересчитать не удалось (метод
    `axis_dependent`, неоднозначный модальный сценарий, дыра в `by_scenario`).
    Возвращаются наружу, а не глотаются: «пересчитано» и «нечего пересчитывать»
    обязаны быть различимы.
    """
    cond = data["conditional_on_scenarios"]
    method = (cond.get("marginal") or {}).get("method", "linear")
    modal_id = (cond.get("marginal") or {}).get("modal_scenario_id")
    if isinstance(modal_id, str) and modal_id.strip().lower() in ("none", ""):
        modal_id = None       # артефакты пишут строку "none", а не null
    by_scenario = cond.get("by_scenario") or {}

    horizons: list[str] = []
    for sid in ["A", "B", "C", "D"]:
        sc = by_scenario.get(sid) or {}
        vals = sc.get("values") or {}
        if vals:
            horizons = _iter_horizons(vals)
            break

    stale: list[StaleMarginal] = []
    skipped_horizons: list[str] = []

    if weights_by_date is not None:
        outside = sorted(hz for hz in horizons if hz not in weights_by_date)
        if outside:
            raise HorizonOutsideMatrix(outside)

    if "marginal" not in cond or cond["marginal"] is None:
        cond["marginal"] = {}
    if "values" not in cond["marginal"] or cond["marginal"]["values"] is None:
        cond["marginal"]["values"] = {}

    marginal_values = cond["marginal"]["values"]

    for hz in horizons:
        hz_weights = weights_by_date[hz] if weights_by_date is not None \
            else new_weights
        new_val = aggregate_marginal_simple(by_scenario, hz_weights, hz, method,
                                            modal_scenario_id=modal_id)
        if new_val is None:
            # Молчаливый пропуск — тот же класс дефекта, что и тихое `{}`:
            # «пересчитано» и «нечего пересчитывать» неразличимы для читателя.
            skipped_horizons.append(hz)
            continue

        old_entry = _lookup_horizon(marginal_values, hz)
        old_val = old_entry.get("central") if isinstance(old_entry, dict) else None

        if old_val is not None and float(old_val) != 0:
            div = abs(float(old_val) - new_val) / abs(float(old_val))
            if div > STALE_THRESHOLD:
                stale.append(StaleMarginal(
                    forecast_file=forecast_file,
                    horizon=hz,
                    old_value=float(old_val),
                    new_value=float(new_val),
                    divergence_pct=round(div * 100, 2),
                ))

        # Update in-place (сохраняем оригинальный ключ, если он уже есть)
        existing_key = None
        for k in list(marginal_values.keys()):
            canon = k.isoformat() if hasattr(k, "isoformat") else str(k)
            if canon == hz:
                existing_key = k
                break

        if existing_key is not None:
            if isinstance(marginal_values[existing_key], dict):
                marginal_values[existing_key]["central"] = round(new_val, 6)
            else:
                marginal_values[existing_key] = {"central": round(new_val, 6)}
        else:
            marginal_values[hz] = {"central": round(new_val, 6)}

    return stale, data, skipped_horizons


# ---------------------------------------------------------------------------
# Stress YAML (macro-scenarios) update
# ---------------------------------------------------------------------------

def _short_sid(sid: Any) -> str:
    """
    Легаси-написание `Sc-A` → канон `A` (решение D5). Без этого прежние веса из
    артефакта 05-09 (ключи `Sc-A..Sc-D`) не сопоставились бы с новыми (`A..D`),
    и `modal_changed` срабатывал бы ЛОЖНО на каждом прогоне против старого
    артефакта — с предупреждением «нужен FCA для нового modal».
    """
    s = str(sid).strip()
    return s[3:] if s.startswith("Sc-") and len(s) > 3 else s


def load_previous_weights(stress_path: Path | None) -> dict[str, float]:
    """
    Прежние веса из macro-scenarios YAML. Возвращает {} если взять неоткуда.

    Два источника, в порядке приоритета:

    1. `run_metadata.weights_snapshot` — его пишет `update_stress_summary`, то
       есть он появляется только у артефактов, прошедших через RECALIBRATE.
    2. `scenarios.{A..D}.probability` — веса в самом артефакте.

    Второй источник добавлен 2026-08-05 (MFC-5): `weights_snapshot` не
    встречается НИ В ОДНОМ из девяти живых `macro-chain/macro-scenarios-*.yaml`
    (их собирает LLM по шаблону цепочки, а не этот скрипт), поэтому
    `old_weights` всегда были пусты, `old_modal` — None, и диагностика «modal
    сменился» не срабатывала никогда. Веса при этом лежат в артефакте рядом.

    Мультидокументные файлы читаются `safe_load_all`: на
    `macro-scenarios-2026-05-04.yaml` прежний `safe_load` падал необработанным
    `ComposerError` — прогон обрывался трейсбеком на ровном месте.
    """
    if stress_path is None or not stress_path.exists():
        return {}
    try:
        with open(stress_path, "r", encoding="utf-8") as f:
            docs = [d for d in yaml.safe_load_all(f) if isinstance(d, dict)]
    except yaml.YAMLError:
        return {}
    data = docs[0] if docs else {}

    snapshot = (data.get("run_metadata") or {}).get("weights_snapshot") or {}
    if snapshot:
        return {_short_sid(k): float(v) for k, v in snapshot.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}

    out: dict[str, float] = {}
    for sid, blk in (data.get("scenarios") or {}).items():
        if not isinstance(blk, dict):
            continue
        p = blk.get("probability", blk.get("p"))
        if isinstance(p, (int, float)) and not isinstance(p, bool):
            out[_short_sid(sid)] = float(p)
    return out


# ---------------------------------------------------------------------------
# Запись YAML: точечная правка поверх исходного текста
# ---------------------------------------------------------------------------

def _plain_dump(data: Any) -> str:
    """Прежний путь записи: полная перезапись через PyYAML."""
    return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                     sort_keys=False)


def _detect_indent(text: str) -> tuple[int, int, int]:
    """(mapping, sequence, offset) по исходному тексту, чтобы ruamel не
    переформатировал неизменённые места. По умолчанию — стиль PyYAML."""
    mapping, seq_offset = 2, 0
    lines = text.splitlines()
    found_map = found_seq = False
    for i, line in enumerate(lines[:-1]):
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        ind = len(line) - len(stripped)
        nxt = lines[i + 1]
        nstripped = nxt.lstrip(" ")
        if not nstripped or nstripped.startswith("#"):
            continue
        nind = len(nxt) - len(nstripped)
        if stripped.endswith(":") and not stripped.startswith("- "):
            if nstripped.startswith("- ") and not found_seq:
                seq_offset, found_seq = nind - ind, True
            elif nind > ind and not nstripped.startswith("- ") and not found_map:
                mapping, found_map = nind - ind, True
        if found_map and found_seq:
            break
    if seq_offset > 0:
        return mapping, seq_offset + 2, seq_offset
    return mapping, 2, 0


def _find_key(node: Any, key: Any) -> Any:
    """Ключ round-trip-документа, соответствующий ключу PyYAML-данных
    (даты в ключах PyYAML и ruamel разбирают в разные типы)."""
    if key in node:
        return key
    for rk in node:
        if str(rk) == str(key):
            return rk
    return key


def _apply_diff(node: Any, old: Any, new: Any) -> Any:
    """Переносит в round-trip-узел только отличия old→new; возвращает узел,
    который родитель должен хранить (тот же при правке на месте)."""
    if isinstance(old, dict) and isinstance(new, dict) and hasattr(node, "keys"):
        for ok in list(old.keys()):
            if ok not in new:
                del node[_find_key(node, ok)]
        for k, nv in new.items():
            if k not in old:
                node[k] = nv
            elif old[k] != nv or type(old[k]) is not type(nv):
                rk = _find_key(node, k)
                node[rk] = _apply_diff(node[rk], old[k], nv)
        return node
    if (isinstance(old, list) and isinstance(new, list)
            and isinstance(node, list) and len(old) == len(new)):
        for i, (ov, nv) in enumerate(zip(old, new)):
            if ov != nv or type(ov) is not type(nv):
                node[i] = _apply_diff(node[i], ov, nv)
        return node
    return new


_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v)


def _num_token(v: Any) -> str:
    """Текст числа, который PyYAML прочитает тем же числом: у экспоненты без
    точки (`1e-05`) PyYAML видит строку, поэтому мантисса дополняется `.0`."""
    t = repr(v)
    if isinstance(v, float) and "e" in t and "." not in t.split("e")[0]:
        mant, exp = t.split("e")
        t = f"{mant}.0e{exp}"
    return t


def _collect_number_edits(node: Any, old: Any, new: Any,
                          out: list[tuple[int, int, Any, Any]]) -> bool:
    """Собирает (строка, столбец, старое, новое) для замен чисел на числа.
    False — есть правка другого рода (строка, ключ, длина списка и т. п.)."""
    if isinstance(old, dict) and isinstance(new, dict) and hasattr(node, "lc"):
        if set(old) != set(new):
            return False
        for k, nv in new.items():
            if old[k] == nv and type(old[k]) is type(nv):
                continue
            rk = _find_key(node, k)
            if isinstance(nv, (dict, list)):
                if not _collect_number_edits(node[rk], old[k], nv, out):
                    return False
            elif _is_num(old[k]) and _is_num(nv):
                line, col = node.lc.value(rk)
                out.append((line, col, old[k], nv))
            else:
                return False
        return True
    if isinstance(old, list) and isinstance(new, list) and hasattr(node, "lc") \
            and len(old) == len(new):
        for i, (ov, nv) in enumerate(zip(old, new)):
            if ov == nv and type(ov) is type(nv):
                continue
            if isinstance(nv, (dict, list)):
                if not _collect_number_edits(node[i], ov, nv, out):
                    return False
            elif _is_num(ov) and _is_num(nv):
                line, col = node.lc.item(i)
                out.append((line, col, ov, nv))
            else:
                return False
        return True
    return False


def _patch_numbers(src: str, doc: Any, old_data: Any, new_data: Any) -> str | None:
    """Правка исходного текста «на месте»: заменяются только токены чисел,
    остальные байты файла не затрагиваются. None — правка не сводится к
    заменам чисел (или токен не найден там, где ожидался)."""
    edits: list[tuple[int, int, Any, Any]] = []
    if not _collect_number_edits(doc, old_data, new_data, edits):
        return None
    lines = src.split("\n")
    for line, col, ov, nv in sorted(edits, reverse=True):
        if line >= len(lines):
            return None
        m = _NUM_RE.match(lines[line], col)
        if m is None:
            return None
        try:
            if float(m.group(0)) != float(ov):
                return None
        except ValueError:
            return None
        lines[line] = lines[line][:col] + _num_token(nv) + lines[line][m.end():]
    return "\n".join(lines)


def _render_preserving(path: Path, old_data: Any, new_data: Any) -> str | None:
    """Текст файла после точечной правки; None — ruamel недоступен или файла нет.

    Сначала замена токенов чисел в исходном тексте (всё остальное побайтно
    прежнее). Если правка шире (строки, ключи, длина списка) — перенос отличий
    в round-trip-документ и его сериализация: комментарии, кавычки и `0.60`
    сохраняются, но многострочные скаляры ruamel склеивает в одну строку."""
    if _RuamelYAML is None or not path.exists():
        return None
    src = path.read_text(encoding="utf-8")
    ry = _RuamelYAML(typ="rt")
    ry.preserve_quotes = True
    ry.width = 10 ** 6
    m, sq, off = _detect_indent(src)
    ry.indent(mapping=m, sequence=sq, offset=off)
    ry.representer.add_representer(
        type(None), lambda rp, _d: rp.represent_scalar(
            "tag:yaml.org,2002:null", "null"))
    doc = ry.load(src)
    patched = _patch_numbers(src, doc, old_data, new_data)
    if patched is not None:
        return patched
    doc = _apply_diff(doc, old_data, new_data)
    buf = io.StringIO()
    ry.dump(doc, buf)
    return buf.getvalue()


def write_yaml_preserving(path: Path, old_data: Any, new_data: Any) -> bool:
    """Записывает new_data в path, сохраняя комментарии и формат неизменённых
    узлов (нужен ruamel.yaml). Без него или без исходного файла — полная
    перезапись PyYAML. Результат перечитывается PyYAML и сверяется с new_data;
    запись атомарная (временный файл + os.replace после успешной сверки),
    при расхождении — ValueError, исходный файл не тронут.

    Возвращает True, если файл переписан целиком (без сохранения формата)."""
    text = _render_preserving(path, old_data, new_data)
    full_rewrite = text is None
    if full_rewrite:
        text = _plain_dump(new_data)
    if yaml.safe_load(text) != new_data:
        raise ValueError(
            f"самопроверка записи {path.name}: перечитанное не совпало с "
            f"расчётом, файл не изменён")
    tmp = path.with_name(path.name + ".tmp-recalibrate")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return full_rewrite


def update_stress_summary(
    stress_path: Path | None,
    new_weights: dict[str, float],
    output_path: Path,
    weights_by_date: dict[str, dict[str, float]] | None = None,
    weights_source: str | None = None,
    weights_meta: dict | None = None,
) -> bool:
    """Обновляет modal_scenario_id, hedge_target, weights_snapshot в stress YAML.

    weights_by_date (MFC-5 шаг 2) дополнительно пишется в
    run_metadata.weights_by_horizon_snapshot — иначе артефакт нёс бы только
    скаляр, и по нему нельзя было бы восстановить, какими весами пересчитан
    каждый горизонт."""
    if stress_path is not None and stress_path.exists():
        with open(stress_path, "r", encoding="utf-8") as f:
            out_data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        out_data = {}

    modal = modal_scenario(new_weights)
    hedge = hedge_target(new_weights)

    out_data["modal_scenario_id"] = modal
    out_data["modal_probability"] = round(new_weights[modal], 6)
    out_data["hedge_target"] = hedge

    if "run_metadata" not in out_data or out_data["run_metadata"] is None:
        out_data["run_metadata"] = {}
    out_data["run_metadata"]["weights_snapshot"] = {
        k: round(v, 6) for k, v in new_weights.items()
    }
    if weights_by_date:
        out_data["run_metadata"]["weights_by_horizon_snapshot"] = {
            dt: {k: round(v, 6) for k, v in w.items()}
            for dt, w in weights_by_date.items()
        }

    if weights_source:
        out_data["run_metadata"]["weights_source"] = weights_source
        if weights_meta:
            out_data["run_metadata"]["weights_source_meta"] = weights_meta

    # Точечная правка — только если выходной файл уже есть; новый выходной файл пишется прежним yaml.dump.
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
        return write_yaml_preserving(output_path, existing, out_data)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(_plain_dump(out_data))
    return True


# ---------------------------------------------------------------------------
# Main recalibrate function
# ---------------------------------------------------------------------------

def recalibrate(
    scenario_yaml_path: Path,
    forecasts_dir: Path | None = None,
    stress_yaml_path: Path | None = None,
    output_path: Path | None = None,
    strict: bool = False,
    site_weights_path: Path | None = None,
    use_site_weights: bool = True,
) -> RecalibrateResult:
    """
    Lazy-режим: читает новые веса, пересчитывает Layer 2 marginals,
    обновляет modal/hedge ranking. Никаких LLM-вызовов.

    Args:
        scenario_yaml_path: SSOT scenario YAML с весами сценариев
        forecasts_dir: директория с forecast YAML (ищет *.yaml)
        stress_yaml_path: текущий macro-scenarios-{date}.yaml (для old_weights)
        output_path: куда писать обновлённый stress YAML (None → не писать)
        strict: True → отказ при stale; False → auto-recalculate с warning
        site_weights_path: явный файл весов сайта (None → соседний `stress-weights-<матрица>.json`)
        use_site_weights: False → только веса матрицы

    Файл сайта есть и годен → веса на все даты прогнозов из него (интерполяция по дням между
    сроками сайта, вне сроков — ближайший срок); скаляр — веса сайта на дату h12 матрицы.
    Есть, но не годен → SiteWeightsRefused. Нет → веса матрицы, как раньше.
    """
    # 1. Read and validate SSOT weights
    new_weights = load_weights(scenario_yaml_path)
    validate_weights(new_weights)
    # MFC-5 шаг 2: горизонтные веса (None — скалярная матрица, прежний путь).
    # Скаляр остаётся источником modal/hedge-диагностики: по конвенции PSS-9
    # он равен весам primary-горизонта.
    weights_by_date = load_horizon_weights(scenario_yaml_path)
    weights_source = "matrix"
    weights_meta: dict = {"source": "matrix", "file": scenario_yaml_path.name}
    site = resolve_site_weights(scenario_yaml_path, new_weights, forecasts_dir,
                                site_weights_path, use_site_weights)
    if site is not None:
        new_weights, weights_by_date, weights_meta = site
        weights_source = "site"
        validate_weights(new_weights)

    # 2. Detect modal change
    old_weights = load_previous_weights(stress_yaml_path)
    old_modal = modal_scenario(old_weights) if old_weights else None
    new_modal = modal_scenario(new_weights)
    modal_changed = old_modal is not None and old_modal != new_modal

    coverage_warning = None
    if modal_changed:
        coverage_warning = (
            f"Modal сценарий сменился: {old_modal} → {new_modal} "
            f"(p={new_weights[new_modal]:.3f}). "
            "Если coverage_quality для нового modal == DERIVED — нужен FCA."
        )

    # 3. Recalculate Layer 2 marginals
    all_stale: list[StaleMarginal] = []
    updated_files: list[str] = []
    skipped_files: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    full_rewrites = 0

    if forecasts_dir is not None and forecasts_dir.exists():
        for forecast_path in sorted(forecasts_dir.glob("*.yaml")):
            try:
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or not has_conditional_block(data):
                    continue

                # Архив не пересчитывается. `superseded`-прогноз ссылается на ТУ ЖЕ
                # матрицу, что и его активный преемник (в этом и состоит механизм
                # supersession), поэтому фильтр по `source_matrix` его не отсеивает.
                # В живой библиотеке 24 из 31 прогноза — superseded, и на матрицу
                # 07-01 ссылаются 15 файлов, из которых 8 архивных. Переписывать их
                # нельзя: retrospective-forecast-audit и калибровочные milestones
                # читают superseded как неизменный исторический снимок — иначе
                # «что мы думали в июле» задним числом станет тем, что мы думаем
                # сейчас, и ошибка прогноза посчитается по подменённым числам.
                # Отсутствие `status` тоже пропуск: неизвестное состояние — не повод
                # писать в файл.
                status = str(data.get("status") or "").strip().lower()
                if status != "active":
                    skipped_files.append(
                        f"{forecast_path.name}: status={status or '—'} (пересчитывается "
                        f"только active)")
                    continue

                mismatch = matrix_matches(data, scenario_yaml_path)
                if mismatch is not None:
                    skipped_files.append(f"{forecast_path.name}: {mismatch}")
                    continue

                # Снимок Layer 2 ДО пересчёта: файл переписывается только если
                # числа реально изменились. `yaml.dump` нормализует форматирование
                # и уносит комментарии, поэтому безусловная перезапись означала бы
                # переформатирование живой библиотеки на каждом прогоне — даже
                # когда пересчитывать нечего (на артефактах 08-05 таких файлов 9
                # из 15: веса 0.25×4 совпадают с теми, на которых они собраны).
                before = _marginal_snapshot(data)
                old_data = copy.deepcopy(data)

                try:
                    stale, updated_data, skipped_hz = recalculate_layer2(
                        data, new_weights, str(forecast_path),
                        weights_by_date=weights_by_date,
                    )
                except HorizonOutsideMatrix as hom:
                    # Решение владельца (STOP-D2 п.3): h18-файлы не трогать.
                    # Их Layer 2 остаётся на ПРЕЖНИХ весах и внешне неотличим
                    # от пересчитанного — поэтому пропуск громкий, не тихий.
                    skipped_files.append(f"{forecast_path.name}: {hom}")
                    continue
                all_stale.extend(stale)
                if skipped_hz:
                    skipped_files.append(
                        f"{forecast_path.name}: горизонты {sorted(skipped_hz)} не "
                        f"пересчитаны (метод не поддержан или модальный сценарий "
                        f"неоднозначен)"
                    )

                after = _marginal_snapshot(updated_data)

                if not strict and after != before:
                    if write_yaml_preserving(forecast_path, old_data, updated_data):
                        full_rewrites += 1
                    updated_files.append(str(forecast_path))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{forecast_path}: {exc}")

    if strict and all_stale:
        raise StaleMarginalError(all_stale)

    # 4. Update stress summary
    if output_path is not None:
        if update_stress_summary(stress_yaml_path, new_weights, output_path,
                                 weights_by_date=weights_by_date,
                                 weights_source=weights_source, weights_meta=weights_meta) \
                and _RuamelYAML is None:
            full_rewrites += 1
        updated_files.append(str(output_path))

    if full_rewrites and _RuamelYAML is None:
        warnings.append(NO_RUAMEL_WARNING)

    return RecalibrateResult(
        old_weights=old_weights,
        new_weights=new_weights,
        modal_changed=modal_changed,
        old_modal=old_modal,
        new_modal=new_modal,
        coverage_warning=coverage_warning,
        stale_recalculated=all_stale,
        updated_files=updated_files,
        skipped_files=skipped_files,
        errors=errors,
        warnings=warnings,
        weights_source=weights_source,
        weights_meta=weights_meta,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _weights_line(result: RecalibrateResult) -> str:
    m = result.weights_meta or {}
    if result.weights_source != "site":
        return f"веса: матрица {m.get('file')} (файла сайта нет или он отключён)"
    return (f"веса: файл сайта {m.get('file')} (заданы {m.get('set_at')}); "
            f"точные даты: {', '.join(m.get('exact') or []) or '—'}; "
            f"интерполированы: {', '.join(m.get('interpolated') or []) or '—'}; "
            f"за пределами сроков сайта — взят ближайший срок: {', '.join(m.get('held') or []) or '—'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "RECALIBRATE-mode для macro-forecast-chain (D7). "
            "Lazy weight update без LLM-вызовов, <30 секунд."
        ),
    )
    parser.add_argument(
        "--scenario", "-s", required=True,
        help="Путь к scenario YAML (SSOT весов)",
    )
    parser.add_argument(
        "--forecasts-dir", "-f", default=None,
        help="Директория с forecast YAML (conditional_on_scenarios)",
    )
    parser.add_argument(
        "--stress", default=None,
        help="Путь к stress YAML (macro-scenarios-{date}.yaml)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Выходной файл (по умолчанию: перезаписывает --stress)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Отказ при stale marginals вместо auto-recalculate",
    )
    parser.add_argument(
        "--site-weights", default=None,
        help="Файл весов сайта (stress-weights@1); по умолчанию соседний stress-weights-<матрица>.json",
    )
    parser.add_argument(
        "--no-site-weights", action="store_true",
        help="Не использовать файл сайта: веса из матрицы (запрет интерполяции, h18-файлы пропускаются)",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Красивый JSON вывод",
    )
    args = parser.parse_args(argv)

    scenario_path = Path(args.scenario)
    forecasts_dir = Path(args.forecasts_dir) if args.forecasts_dir else None
    stress_path = Path(args.stress) if args.stress else None
    output_path = (
        Path(args.output) if args.output
        else stress_path
    )

    try:
        result = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=forecasts_dir,
            stress_yaml_path=stress_path,
            output_path=output_path,
            strict=args.strict,
            site_weights_path=Path(args.site_weights) if args.site_weights else None,
            use_site_weights=not args.no_site_weights,
        )
    except SiteWeightsRefused as e:
        print(f"ERROR: {e}\nПодсказка: --no-site-weights считает по весам матрицы.", file=sys.stderr)
        return 1
    except StaleMarginalError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except WeightValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if result.coverage_warning:
        print(f"WARNING: {result.coverage_warning}", file=sys.stderr)

    print(_weights_line(result), file=sys.stderr)

    for s in result.stale_recalculated:
        print(
            f"INFO: auto-recalculated {s.forecast_file} [{s.horizon}]: "
            f"{s.old_value:.4f} → {s.new_value:.4f} ({s.divergence_pct:.1f}%)",
            file=sys.stderr,
        )

    # Пропуски печатаются наравне со сделанным: «пересчитано 5 из 31» и
    # «пересчитано всё» — разные новости, и молчание выдало бы второе за первое.
    for skip in result.skipped_files:
        print(f"SKIP: {skip}", file=sys.stderr)

    for warn in result.warnings:
        print(f"WARN: {warn}", file=sys.stderr)

    for err in result.errors:
        print(f"ERROR (non-fatal): {err}", file=sys.stderr)

    indent = 2 if args.pretty else None
    print(json.dumps(asdict(result), ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
