"""Детектор выхода за обучающий диапазон — задача 35, §5.2.

«Возвращается вместе с прогнозом, **всегда, не опцией**. Организаторы
назвали его критерием масштабируемости [10.08 35:40]».

Это требование к форме выхода, и здесь оно выполнено типом, а не
договорённостью: `ScoredPrediction` не собирается без `ood`, обоих полей
обязательных, — модель, вернувшая прогноз без оценки, не проходит
конструктор. Приёмка проверяет именно это, а не то, что кто-то помнит
позвать детектор.

## Что именно детектируется

Вход суррогата выводится из одного `Schedule` и не содержит ни одного числа
от симулятора (задача 32). Значит и обучающая область — это область
**расписаний**, а не откликов, и «выход за диапазон» проверяется по тем же
признакам, которыми модель кормится: уставки, накопления, закачка соседей,
статика скважины и три категориальных состояния.

Область запоминается двумя способами, потому что признаки двух разных родов:

- **числовые** — интервалом `[low, high]`, замеренным по обучающей выборке;
  оценка равна тому, на сколько ширин интервала значение вышло наружу;
- **категориальные** (`Availability`, `Role`, `OperatingStatus`) — множеством
  встреченных значений; невиданное значение это не «далеко», а «вне» — у
  такой точки оценка бесконечна, и никакой порог `τ` её не пропустит.

## Максимум, а не среднее

`ood_score` — максимум по узлам и признакам, и это не деталь реализации.
Экстраполяция по одной скважине из 103 при усреднении растворяется в
нулях: 1/103 от порога, то есть «внутри области» при том, что модель по
этой скважине не видела ничего похожего. Область доверия §10.2 (`ood_score
≤ τ`) осмысленна только при худшем-случайном агрегировании.

По той же причине оценка сопровождается `worst` и полным списком выходов:
цикл верификации обязан уметь сказать не только «кандидат вне области», но
и какая скважина на каком шаге его туда вывела.

## Нулевой ширины интервал

Признак, у которого в обучении было ровно одно значение, ширины не имеет.
Делить на неё нельзя, а объявить любое отклонение бесконечным — значит
отвергнуть всё. Такой признак сравнивается на точное равенство: совпало —
ноль, не совпало — бесконечность, как у категориального. Это честнее
любого подобранного эпсилона: обучающая выборка про соседние значения
действительно ничего не знает.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from surrogate.features import SurrogateInput, WellStepFeatures
from surrogate.raw_model_output import RawModelOutput

# Числовые признаки узла. Имена совпадают с полями WellStepFeatures — это
# не косметика: имя признака уезжает в диагностику цикла верификации, и
# сверять его с исходным полем должно быть можно глазами, без словаря.
NUMERIC_FEATURES: tuple[str, ...] = (
    "setpoint_m3_per_day",
    "effective_target_rate_m3_per_day",
    "cumulative_target_liquid_m3",
    "cumulative_target_injection_m3",
    "cumulative_neighbor_injection_m3",
    "current_neighbor_injection_m3_per_day",
    "event_count",
    "fixed_event_count",
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "availability",
    "role",
    "operating_status",
)


class OodError(ValueError):
    """Область нельзя построить или применить: пустая выборка, разошедшаяся статика."""


@dataclass(frozen=True, slots=True)
class FeatureRange:
    """Замеренный интервал одного числового признака."""

    name: str
    low: float
    high: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.low) or not math.isfinite(self.high):
            raise OodError(f"{self.name}: границы не конечны ({self.low}, {self.high})")
        if self.high < self.low:
            raise OodError(f"{self.name}: high {self.high} < low {self.low}")

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def degenerate(self) -> bool:
        """В обучении признак принимал ровно одно значение."""

        return self.width == 0.0

    def exceedance(self, value: float) -> float:
        """На сколько ширин интервала значение вышло наружу. Внутри — ноль."""

        if not math.isfinite(value):
            return math.inf
        if self.low <= value <= self.high:
            return 0.0
        if self.degenerate:
            # Ширины нет — соседние значения обучающей выборке неизвестны.
            return math.inf
        distance = self.low - value if value < self.low else value - self.high
        return distance / self.width


@dataclass(frozen=True, slots=True)
class TrainingDomain:
    """Обучающая область: что модель видела.

    `schedule_hashes` — provenance, не украшение: область, замеренная на
    одном датасете, не описывает другой, и `OptimizerResult.provenance`
    (§6.1) обязан уметь связать `ood_score` с версией датасета.
    """

    ranges: tuple[FeatureRange, ...]
    categories: tuple[tuple[str, frozenset[str]], ...]
    static_feature_names: tuple[str, ...]
    n_nodes: int
    schedule_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.n_nodes < 1:
            raise OodError("обучающая область не строится по пустой выборке")

    def range_of(self, name: str) -> FeatureRange:
        for item in self.ranges:
            if item.name == name:
                return item
        raise OodError(f"признака {name!r} нет в обучающей области")

    def categories_of(self, name: str) -> frozenset[str]:
        for key, values in self.categories:
            if key == name:
                return values
        raise OodError(f"категориального признака {name!r} нет в обучающей области")


@dataclass(frozen=True, slots=True)
class Exceedance:
    """Один выход за диапазон: где, какой признак, на сколько."""

    feature: str
    well: str
    control_step: int
    value: float
    low: float
    high: float
    score: float


@dataclass(frozen=True, slots=True)
class OodScore:
    """Оценка выхода за обучающий диапазон.

    `score` — максимум по всем узлам и признакам: ноль означает, что
    кандидат целиком внутри области, положительное — на сколько ширин
    интервала вышел худший признак, `inf` — встретилось невиданное
    категориальное значение или признак с нулевой шириной изменился.
    """

    score: float
    exceedances: tuple[Exceedance, ...]
    n_nodes: int

    @property
    def worst(self) -> Exceedance | None:
        return self.exceedances[0] if self.exceedances else None

    def inside(self, tau: float) -> bool:
        """Область доверия §10.2: кандидат допустим, пока `ood_score ≤ τ`."""

        if tau < 0.0:
            raise OodError(f"порог области доверия τ={tau} отрицателен")
        return self.score <= tau


@dataclass(frozen=True, slots=True)
class ScoredPrediction:
    """Прогноз и его `ood_score`, неразделимо.

    §5.2 требует, чтобы детектор возвращался вместе с прогнозом всегда, а
    не опцией. Здесь это обеспечено конструктором: у обоих полей нет
    значения по умолчанию, и прогноз без оценки собрать нечем.
    """

    output: RawModelOutput
    ood: OodScore


def _numeric(node: WellStepFeatures, name: str) -> float:
    return float(getattr(node, name))


def _categorical(node: WellStepFeatures, name: str) -> str:
    return getattr(node, name).value


def _static_names(inputs: Sequence[SurrogateInput]) -> tuple[str, ...]:
    names = inputs[0].static_feature_names
    for other in inputs[1:]:
        if other.static_feature_names != names:
            raise OodError(
                "состав статических признаков разошёлся между расписаниями: "
                f"{names} против {other.static_feature_names}"
            )
    return names


def fit_domain(inputs: Sequence[SurrogateInput]) -> TrainingDomain:
    """Замерить обучающую область по входам датасета.

    Берутся именно `SurrogateInput` — то, чем модель кормится, — а не
    отклики: вход суррогата не содержит ни одного числа от симулятора
    (задача 32), и область обязана быть областью того же пространства.
    """

    if not inputs:
        raise OodError("обучающая область не строится по пустой выборке")

    static_names = _static_names(inputs)
    lows: dict[str, float] = {}
    highs: dict[str, float] = {}
    seen: dict[str, set[str]] = {name: set() for name in CATEGORICAL_FEATURES}
    n_nodes = 0

    for item in inputs:
        for node in item.nodes:
            n_nodes += 1
            if len(node.static_values) != len(static_names):
                raise OodError(
                    f"скважина {node.well}: статических значений "
                    f"{len(node.static_values)} против {len(static_names)} имён"
                )
            for name in NUMERIC_FEATURES:
                value = _numeric(node, name)
                if not math.isfinite(value):
                    raise OodError(f"скважина {node.well}: {name}={value!r} не конечно")
                lows[name] = value if name not in lows else min(lows[name], value)
                highs[name] = value if name not in highs else max(highs[name], value)
            for index, name in enumerate(static_names):
                key = f"static:{name}"
                value = float(node.static_values[index])
                if not math.isfinite(value):
                    raise OodError(f"скважина {node.well}: {key}={value!r} не конечно")
                lows[key] = value if key not in lows else min(lows[key], value)
                highs[key] = value if key not in highs else max(highs[key], value)
            for name in CATEGORICAL_FEATURES:
                seen[name].add(_categorical(node, name))

    if n_nodes == 0:
        raise OodError("во входах датасета нет ни одного узла")

    ranges = tuple(
        FeatureRange(name=name, low=lows[name], high=highs[name])
        for name in sorted(lows)
    )
    categories = tuple(
        (name, frozenset(values)) for name, values in sorted(seen.items())
    )
    return TrainingDomain(
        ranges=ranges,
        categories=categories,
        static_feature_names=static_names,
        n_nodes=n_nodes,
        schedule_hashes=tuple(item.canonical_schedule_hash for item in inputs),
    )


def score(candidate: SurrogateInput, domain: TrainingDomain) -> OodScore:
    """Оценить, насколько кандидат выходит за обучающую область.

    Возвращается всегда: точка внутри области получает `score = 0.0` и
    пустой список выходов, а не `None`. Отсутствие оценки и оценка «внутри»
    — разные вещи, и потребитель не должен их различать по `is None`.
    """

    if candidate.static_feature_names != domain.static_feature_names:
        raise OodError(
            "состав статических признаков кандидата не совпадает с обучающим: "
            f"{candidate.static_feature_names} против {domain.static_feature_names}"
        )

    exceedances: list[Exceedance] = []
    n_nodes = 0

    for node in candidate.nodes:
        n_nodes += 1
        for name in NUMERIC_FEATURES:
            interval = domain.range_of(name)
            value = _numeric(node, name)
            amount = interval.exceedance(value)
            if amount > 0.0:
                exceedances.append(
                    Exceedance(
                        feature=name,
                        well=node.well,
                        control_step=node.control_step,
                        value=value,
                        low=interval.low,
                        high=interval.high,
                        score=amount,
                    )
                )
        for index, name in enumerate(domain.static_feature_names):
            key = f"static:{name}"
            interval = domain.range_of(key)
            value = float(node.static_values[index])
            amount = interval.exceedance(value)
            if amount > 0.0:
                exceedances.append(
                    Exceedance(
                        feature=key,
                        well=node.well,
                        control_step=node.control_step,
                        value=value,
                        low=interval.low,
                        high=interval.high,
                        score=amount,
                    )
                )
        for name in CATEGORICAL_FEATURES:
            allowed = domain.categories_of(name)
            value = _categorical(node, name)
            if value not in allowed:
                # Невиданная категория — не «далеко», а «вне»: расстояния
                # между значениями перечисления не существует.
                exceedances.append(
                    Exceedance(
                        feature=name,
                        well=node.well,
                        control_step=node.control_step,
                        value=math.nan,
                        low=math.nan,
                        high=math.nan,
                        score=math.inf,
                    )
                )

    if n_nodes == 0:
        raise OodError("кандидат не содержит ни одного узла")

    exceedances.sort(key=lambda item: (-item.score, item.control_step, item.well))
    worst = exceedances[0].score if exceedances else 0.0
    return OodScore(score=worst, exceedances=tuple(exceedances), n_nodes=n_nodes)


def predict_with_score(
    output: RawModelOutput, candidate: SurrogateInput, domain: TrainingDomain
) -> ScoredPrediction:
    """Единственный способ выпустить прогноз наружу.

    Функция существует, чтобы у вызывающей стороны не было короткого пути
    «вернуть только `RawModelOutput`»: §5.2 требует оценку всегда, и
    удобная дверь мимо неё — то самое, чем «не опцией» превращается в
    «опцию» через две недели.
    """

    return ScoredPrediction(output=output, ood=score(candidate, domain))


def worst_offenders(assessment: OodScore, limit: int = 5) -> tuple[Exceedance, ...]:
    """Первые `limit` выходов по убыванию — то, что цикл верификации
    показывает человеку, когда кандидат отвергнут областью доверия."""

    if limit < 1:
        raise OodError(f"limit={limit} < 1")
    return assessment.exceedances[:limit]


def domain_of_inputs(inputs: Iterable[SurrogateInput]) -> TrainingDomain:
    """`fit_domain` для ленивого источника: датасет отдаёт входы потоком."""

    return fit_domain(tuple(inputs))
