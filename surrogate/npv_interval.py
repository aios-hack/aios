"""Калиброванный интервал ЧДД и нижняя доверительная граница — гейт 6.

Приёмочный гейт «uncertainty calibration» требует, чтобы заявленный интервал
имел **подтверждённое** покрытие. Сегодня у головы ЧДД нет никакой оценки
неопределённости: она возвращает одно число. Из-за этого невозможен
консервативный отбор кандидатов `ЧДД − β·σ`, на котором стоит весь контур
доверенной области: сравнивать кандидатов приходится по среднему, а среднее
оптимизатор эксплуатирует.

Метод — split conformal: абсолютные остатки на калибровочной выборке,
квантиль `⌈(n+1)·level⌉/n`, интервал `прогноз ± q`. Гарантия маргинальная и
держится при одном условии — калибровочные сценарии **обменяемы** с теми, на
которых интервал будет применяться.

## Почему нельзя калибровать по validation

`BlockKernelNpvHead` обучается на train+validation
(`tools/surrogate_fit_locked_npv_candidate.py`), поэтому остатки на validation
внутривыборочные. Замер это подтверждает: медиана |ошибки| головы на
validation 14.0 млн ₽, на test 33.6 млн ₽; на семействе `UNREACHABLE` разрыв
десятикратный — 7.2 против 75.8 млн ₽, тогда как у гребневой регрессии,
обученной только на train, то же семейство даёт 62.5 и 59.7, то есть ведёт
себя одинаково.

Интервал, откалиброванный по validation, наследует этот оптимизм и недокрывает:

| Заявлено | Фактическое покрытие на test |
|---|---|
| 80% | 59.0% |
| 90% | 73.3% |
| 95% | 80.0% |

Поэтому конструктор **отказывается** принимать выборку, помеченную как
участвовавшая в обучении. Это не перестраховка: молча выдать интервал,
который покрывает 59% вместо 80%, опаснее, чем не выдать никакого.

## Что достижимо на честной выборке

Гребневая регрессия, обученная на 390 сценариях train, откалиброванная на
100 отложенных сценариях того же train:

| Заявлено | validation | test |
|---|---|---|
| 80% | 69.5% | 70.5% |
| 90% | 82.9% | 84.8% |
| 95% | 96.2% | 93.3% |

Покрытие всё ещё ниже заявленного на низких уровнях. Поэтому отчёт несёт
**измеренное** покрытие рядом с номинальным, и предъявлять следует именно
измеренное.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

FORMAT = "aios.surrogate-npv-conformal-interval.v1"

# Минимум калибровочных сценариев. При n меньше девятнадцати конформный
# квантиль уровня 0.95 попадает на последний элемент выборки, то есть
# вырождается в максимум остатка и гарантии не даёт.
MIN_CALIBRATION_SCENARIOS = 20


class NpvIntervalError(ValueError):
    """Интервал нельзя построить или нельзя ему верить."""


@dataclass(frozen=True, slots=True)
class CoverageCheck:
    """Измеренное покрытие на выборке, которой калибровка не касалась."""

    population: str
    n_scenarios: int
    level: float
    covered: int

    @property
    def coverage(self) -> float:
        return self.covered / self.n_scenarios

    @property
    def shortfall(self) -> float:
        """Насколько фактическое покрытие ниже заявленного. Отрицательное — запас."""

        return self.level - self.coverage

    def as_dict(self) -> dict[str, object]:
        return {
            "population": self.population,
            "n_scenarios": self.n_scenarios,
            "level": self.level,
            "covered": self.covered,
            "coverage": self.coverage,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True, slots=True)
class ConformalNpvInterval:
    """Полуширина интервала ЧДД, полученная из отложенных остатков.

    ``half_width_rub`` — единственный параметр модели неопределённости.
    Он не подгоняется ни под что: это порядковая статистика остатков.
    """

    level: float
    half_width_rub: float
    n_calibration: int
    calibration_population: str
    format: str = FORMAT

    def __post_init__(self) -> None:
        if not 0.0 < self.level < 1.0:
            raise NpvIntervalError("уровень доверия должен лежать в (0, 1)")
        if not math.isfinite(self.half_width_rub) or self.half_width_rub < 0.0:
            raise NpvIntervalError("полуширина должна быть конечной и неотрицательной")
        if self.n_calibration < MIN_CALIBRATION_SCENARIOS:
            raise NpvIntervalError(
                f"калибровка на {self.n_calibration} сценариях не даёт гарантии: "
                f"нужно минимум {MIN_CALIBRATION_SCENARIOS}"
            )
        if not self.calibration_population:
            raise NpvIntervalError(
                "калибровочная выборка обязана быть названа: без этого нельзя "
                "проверить, что она не участвовала в обучении"
            )

    @classmethod
    def fit(
        cls,
        actual_rub: Sequence[float],
        predicted_rub: Sequence[float],
        *,
        level: float,
        population: str,
        population_used_in_training: bool,
    ) -> "ConformalNpvInterval":
        """Квантиль абсолютных остатков на выборке, не участвовавшей в обучении.

        ``population_used_in_training`` обязателен и не имеет умолчания: вызов
        должен подтвердить происхождение выборки явно. Ошибка здесь не видна
        в числах — интервал выглядит нормально и молча недокрывает.
        """

        if population_used_in_training:
            raise NpvIntervalError(
                f"выборка {population!r} участвовала в обучении: конформная "
                "калибровка по ней даёт заниженный интервал (замер: 80% "
                "заявленных дали 59% фактических)"
            )
        if len(actual_rub) != len(predicted_rub):
            raise NpvIntervalError("факт и прогноз разной длины")
        residuals = sorted(
            abs(a - p) for a, p in zip(actual_rub, predicted_rub, strict=True)
        )
        if not residuals:
            raise NpvIntervalError("пустая калибровочная выборка")
        if any(not math.isfinite(value) for value in residuals):
            raise NpvIntervalError("остатки содержат неконечные значения")
        size = len(residuals)
        index = min(size, math.ceil((size + 1) * level))
        return cls(
            level=level,
            half_width_rub=residuals[index - 1],
            n_calibration=size,
            calibration_population=population,
        )

    def interval(self, predicted_rub: float) -> tuple[float, float]:
        return (
            predicted_rub - self.half_width_rub,
            predicted_rub + self.half_width_rub,
        )

    def lower_bound(self, predicted_rub: float) -> float:
        """Нижняя доверительная граница — то, по чему ранжируются кандидаты.

        Контур доверенной области сравнивает кандидатов по ней, а не по
        среднему: среднее оптимизатор эксплуатирует, нижнюю границу — нет,
        потому что расширить её можно только уменьшив неопределённость.
        """

        return predicted_rub - self.half_width_rub

    def check_coverage(
        self,
        actual_rub: Sequence[float],
        predicted_rub: Sequence[float],
        *,
        population: str,
    ) -> CoverageCheck:
        """Доля фактов, попавших в интервал. Считается на третьей выборке."""

        if population == self.calibration_population:
            raise NpvIntervalError(
                "покрытие нельзя мерить на той же выборке, что калибровала интервал"
            )
        covered = sum(
            1
            for a, p in zip(actual_rub, predicted_rub, strict=True)
            if abs(a - p) <= self.half_width_rub
        )
        return CoverageCheck(
            population=population,
            n_scenarios=len(actual_rub),
            level=self.level,
            covered=covered,
        )

    def as_dict(self, coverage: Sequence[CoverageCheck] = ()) -> dict[str, object]:
        return {
            "format": self.format,
            "level": self.level,
            "half_width_rub": self.half_width_rub,
            "half_width_mln_rub": self.half_width_rub / 1e6,
            "n_calibration": self.n_calibration,
            "calibration_population": self.calibration_population,
            "measured_coverage": [item.as_dict() for item in coverage],
        }


def lower_bounds(
    interval: ConformalNpvInterval, predicted_rub: Sequence[float]
) -> tuple[float, ...]:
    """Нижние границы пачкой — вход ранжирования в контуре отбора."""

    return tuple(interval.lower_bound(value) for value in predicted_rub)


__all__ = [
    "ConformalNpvInterval",
    "CoverageCheck",
    "FORMAT",
    "MIN_CALIBRATION_SCENARIOS",
    "NpvIntervalError",
    "lower_bounds",
]
