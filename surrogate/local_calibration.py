"""Локальная калибровка ЧДД по якорным прогонам кейса.

Суррогат обучен на одном режиме, а контур предлагает кандидатов в другом.
Замер на восьми кандидатах с настоящим ЧДД OPM: **порядок восстанавливается
идеально** (Spearman +1.0000), а величина промахивается на **431% по медиане**
— модель выдаёт от −2.2 до −20.8 млрд ₽ там, где OPM даёт от +1.4 до +6.1.

Это не шум и не поломка: это сдвиг домена, и он лечится не переобучением, а
локальной поправкой по точкам самого кейса. Аффинная калибровка, проверенная
leave-one-out на тех же восьми точках, снижает медианную ошибку с 431% до
**24.8%** — в семнадцать раз.

## Чем это не является

24.8% — не два процента. Порог дисквалификации по расхождению заявленного и
посчитанного ЧДД — «пара процентов», поэтому калиброванная величина **не
становится сдаваемым числом**: его по-прежнему даёт только собственный прогон
OPM того расписания, которое сдаётся.

Калибровка нужна там, где нужна сопоставимая величина, а не точная: чтобы
сравнить кандидата с проверенным incumbent по нижней доверительной границе и
решить, стоит ли тратить на него пятнадцать минут симулятора.

Поэтому объект несёт свою измеренную LOO-ошибку рядом со значением и не даёт
себя применить, не сообщив её.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence

FORMAT = "aios.surrogate-local-npv-calibration.v1"

# Аффинная поправка имеет два параметра; leave-one-out обучается на n−1 точке,
# поэтому для оценки остатка нужно минимум четыре якоря. При трёх LOO обучается
# на двух точках и проходит через них точно — оценка ошибки выродится в ноль и
# соврёт.
MIN_ANCHORS = 4


class LocalCalibrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LeaveOneOut:
    """Честная оценка ошибки: каждая точка предсказана моделью без неё."""

    median_relative_error_pct: float
    max_relative_error_pct: float
    median_absolute_error_rub: float
    n_anchors: int

    def as_dict(self) -> dict[str, object]:
        return {
            "median_relative_error_pct": self.median_relative_error_pct,
            "max_relative_error_pct": self.max_relative_error_pct,
            "median_absolute_error_rub": self.median_absolute_error_rub,
            "median_absolute_error_mln_rub": self.median_absolute_error_rub / 1e6,
            "n_anchors": self.n_anchors,
        }


@dataclass(frozen=True, slots=True)
class LocalNpvCalibration:
    """Аффинная поправка `slope · прогноз + intercept`, снятая с якорей кейса."""

    slope: float
    intercept_rub: float
    case: str
    leave_one_out: LeaveOneOut
    format: str = FORMAT

    def __post_init__(self) -> None:
        if not math.isfinite(self.slope) or self.slope <= 0.0:
            raise LocalCalibrationError(
                "наклон должен быть конечным и положительным: отрицательный "
                "перевернул бы порядок кандидатов, ради которого суррогат и нужен"
            )
        if not math.isfinite(self.intercept_rub):
            raise LocalCalibrationError("сдвиг должен быть конечным")
        if not self.case:
            raise LocalCalibrationError(
                "калибровка обязана быть привязана к кейсу: перенос поправки "
                "на другую историю не проверялся и не разрешён"
            )

    @classmethod
    def fit(
        cls,
        surrogate_npv_rub: Sequence[float],
        opm_npv_rub: Sequence[float],
        *,
        case: str,
    ) -> "LocalNpvCalibration":
        """Наименьшие квадраты по якорям плюс leave-one-out на тех же точках."""

        if len(surrogate_npv_rub) != len(opm_npv_rub):
            raise LocalCalibrationError("прогнозы и факты разной длины")
        size = len(surrogate_npv_rub)
        if size < MIN_ANCHORS:
            raise LocalCalibrationError(
                f"якорей {size}: аффинная поправка требует минимум {MIN_ANCHORS}, "
                "иначе leave-one-out проходит через точки и ошибку не измеряет"
            )
        if any(
            not math.isfinite(value)
            for value in (*surrogate_npv_rub, *opm_npv_rub)
        ):
            raise LocalCalibrationError("якоря содержат неконечные значения")

        slope, intercept = _least_squares(surrogate_npv_rub, opm_npv_rub)
        relative: list[float] = []
        absolute: list[float] = []
        for index in range(size):
            rest_x = [v for i, v in enumerate(surrogate_npv_rub) if i != index]
            rest_y = [v for i, v in enumerate(opm_npv_rub) if i != index]
            fold_slope, fold_intercept = _least_squares(rest_x, rest_y)
            predicted = fold_slope * surrogate_npv_rub[index] + fold_intercept
            error = abs(predicted - opm_npv_rub[index])
            absolute.append(error)
            if opm_npv_rub[index] != 0.0:
                relative.append(error / abs(opm_npv_rub[index]) * 100.0)
        if not relative:
            raise LocalCalibrationError("все якоря имеют нулевой ЧДД")

        return cls(
            slope=slope,
            intercept_rub=intercept,
            case=case,
            leave_one_out=LeaveOneOut(
                median_relative_error_pct=statistics.median(relative),
                max_relative_error_pct=max(relative),
                median_absolute_error_rub=statistics.median(absolute),
                n_anchors=size,
            ),
        )

    def apply(self, surrogate_npv_rub: float) -> float:
        return self.slope * surrogate_npv_rub + self.intercept_rub

    def submission_grade(self, tolerance_pct: float = 2.0) -> bool:
        """Годится ли калиброванная величина как заявляемое число.

        Организаторы дисквалифицируют за расхождение заявленного и посчитанного
        ЧДД сверх «пары процентов». Замеренная LOO-ошибка 24.8% отвечает на это
        однозначно, и метод существует, чтобы ответ нельзя было обойти
        умолчанием.
        """

        return self.leave_one_out.median_relative_error_pct <= tolerance_pct

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "case": self.case,
            "slope": self.slope,
            "intercept_rub": self.intercept_rub,
            "intercept_mln_rub": self.intercept_rub / 1e6,
            "leave_one_out": self.leave_one_out.as_dict(),
            "submission_grade": self.submission_grade(),
        }


def _least_squares(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    sxx = sum((value - mean_x) ** 2 for value in xs)
    if sxx <= 0.0:
        raise LocalCalibrationError(
            "все якоря получили одинаковый прогноз: наклон не определён"
        )
    sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(xs, ys, strict=True))
    slope = sxy / sxx
    return slope, mean_y - slope * mean_x


__all__ = [
    "FORMAT",
    "MIN_ANCHORS",
    "LeaveOneOut",
    "LocalCalibrationError",
    "LocalNpvCalibration",
]
