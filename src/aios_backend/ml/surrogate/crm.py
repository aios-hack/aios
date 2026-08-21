"""CRM — базовая линия суррогата. Задача 31, docs/context/08_contracts.md §5.5.

CRM (Capacitance-Resistance Model) здесь не физическая основа решения:
`07_concept.md` §5.1.3 закрыл этот вопрос — связность измеряется планом
эксперимента, а не выводится моделью. CRM остаётся ровно двумя вещами:

1. **Базовой линией.** Порог, который обязана бить любая модель, иначе она
   отвергается. Считается за день, без внешних зависимостей.
2. **Источником ограничения материального баланса.** Закачанная вода не
   может дойти до соседей в объёме больше закачанного — у CRM это условие
   на коэффициенты аллокации, и здесь оно накладывается **в ходе подгонки**,
   а не проверкой постфактум.

Модель на интервале управления `k` для добывающей `p`:

    liquid[p][k] = base[p] + Σ_i f[p][i] * filtered_injection[i][k]

`f[p][i]` — коэффициент аллокации: доля воды нагнетательной `i`, доходящая
до `p`. `filtered_injection` — закачка, пропущенная через апериодическое
звено первого порядка с временной константой `tau` (это и есть «capacitance»
CRM: пласт отвечает на закачку не мгновенно).

**Два ограничения, оба физические, оба несущие.**

- `f[p][i] >= 0`: вода не может отбирать жидкость у соседа. Без него
  подгонка на 42 свободных коэффициента запоминает обучающий кусок и
  разваливается на отложенном (замерено: holdout R² −5.3 против +0.87).
- `Σ_p f[p][i] <= 1`: материальный баланс по столбцу. Ограничение по
  столбцу, а не по строке — делится вода одной нагнетательной между
  добывающими, а не наоборот. Накладывается внутри цикла подгонки:
  пересчёт коэффициентов уже сошедшейся неограниченной подгонки ломает
  прогноз (замерено: R² −2.56), потому что base[p] остаётся подогнанным
  под непересчитанные коэффициенты.

**Качество меряется на отложенной части, не на обучающей.** Ось времени
режется на префикс (подгонка) и суффикс (замер): `train_intervals`
интервалов на подгонку, остальные на замер. Метрики считаются только на
суффиксе; метрики на префиксе возвращаются отдельным полем — они не
приёмка, а диагностика переобучения.

Метрики те же, что потом обязан показать суррогат (§5.5): ранговая
корреляция Спирмена, R², MAE и медианная относительная ошибка. Сравнение
делается функцией `compare_to_baseline`.

Оси и типы — контрактные: на вход `IntervalResponse[224]`, никаких
собственных представлений отклика.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from aios_backend.core.contracts import IntervalResponse, N_INTERVALS


class CrmError(ValueError):
    """Отклик или параметры не позволяют построить корректную базовую линию."""


DEFAULT_TAU_INTERVALS = 1.0
DEFAULT_RIDGE = 1e2
DEFAULT_TRAIN_FRACTION = 0.75
_MAX_SWEEPS = 200
_CONVERGENCE_TOLERANCE = 1e-9
_MIN_TAU = 1e-6


@dataclass(frozen=True, slots=True)
class CrmSplit:
    """Разрез оси времени на подгонку и замер. Суффикс — отложенная часть."""

    train_intervals: int
    n_intervals: int

    def __post_init__(self) -> None:
        if self.n_intervals <= 0:
            raise CrmError("n_intervals должен быть положительным")
        if not (0 < self.train_intervals < self.n_intervals):
            raise CrmError(
                f"train_intervals={self.train_intervals} должен лежать строго внутри "
                f"0…{self.n_intervals}: иначе отложенной части не существует"
            )

    @property
    def holdout_intervals(self) -> int:
        return self.n_intervals - self.train_intervals

    @property
    def train_steps(self) -> range:
        return range(self.train_intervals)

    @property
    def holdout_steps(self) -> range:
        return range(self.train_intervals, self.n_intervals)


@dataclass(frozen=True, slots=True)
class CrmMetrics:
    """Метрики одного куска оси времени. Те же величины меряет суррогат."""

    n_points: int
    r2: float
    mae: float
    median_relative_error: float
    spearman_rank_correlation: float


@dataclass(frozen=True, slots=True)
class CrmModel:
    """Подогнанная базовая линия: аллокация, отклик пласта, разрез оси."""

    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    allocation: tuple[tuple[float, ...], ...]
    base_liquid: tuple[float, ...]
    tau_intervals: float
    split: CrmSplit
    material_balance_enforced: bool

    def allocation_of(self, producer: str, injector: str) -> float:
        try:
            row = self.producers.index(producer)
            column = self.injectors.index(injector)
        except ValueError as error:
            raise CrmError(f"пара ({producer!r}, {injector!r}) вне осей модели") from error
        return self.allocation[row][column]

    def injector_allocation_sums(self) -> tuple[float, ...]:
        return tuple(
            sum(self.allocation[row][column] for row in range(len(self.producers)))
            for column in range(len(self.injectors))
        )

    def max_injector_allocation_sum(self) -> float:
        sums = self.injector_allocation_sums()
        return max(sums) if sums else 0.0


@dataclass(frozen=True, slots=True)
class CrmEvaluation:
    """Результат приёмки: отложенная часть — приёмка, обучающая — диагностика."""

    model: CrmModel
    holdout: CrmMetrics
    train: CrmMetrics

    @property
    def generalization_gap(self) -> float:
        return self.train.r2 - self.holdout.r2


def _filtered(series: Sequence[float], tau: float) -> tuple[float, ...]:
    if tau < _MIN_TAU:
        raise CrmError(f"tau={tau} слишком мала: апериодическое звено вырождается")
    alpha = 1.0 / tau
    if alpha > 1.0:
        alpha = 1.0
    out: list[float] = []
    previous = series[0] if series else 0.0
    for value in series:
        previous = previous + alpha * (value - previous)
        out.append(previous)
    return tuple(out)


def _rank(values: Sequence[float]) -> tuple[float, ...]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return tuple(ranks)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    n = len(left)
    if n < 2:
        return 0.0
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    var_left = sum((a - mean_left) ** 2 for a in left)
    var_right = sum((b - mean_right) ** 2 for b in right)
    if var_left <= 0.0 or var_right <= 0.0:
        return 0.0
    return covariance / (var_left * var_right) ** 0.5


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    """Ранговая корреляция — сдаваемая метрика §5.2, со связками через средний ранг."""

    if len(left) != len(right):
        raise CrmError("ранговая корреляция требует совпадающих длин")
    return _pearson(_rank(left), _rank(right))


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> CrmMetrics:
    n = len(actual)
    if n == 0:
        raise CrmError("метрики не считаются на пустой выборке")
    mean_actual = sum(actual) / n
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    total = sum((a - mean_actual) ** 2 for a in actual)
    r2 = 1.0 - residual / total if total > 0.0 else 0.0
    mae = sum(abs(a - p) for a, p in zip(actual, predicted)) / n
    relative = sorted(
        abs(a - p) / abs(a) for a, p in zip(actual, predicted) if a != 0.0
    )
    if relative:
        middle = len(relative) // 2
        median_relative = (
            relative[middle]
            if len(relative) % 2
            else (relative[middle - 1] + relative[middle]) / 2.0
        )
    else:
        median_relative = 0.0
    return CrmMetrics(
        n_points=n,
        r2=r2,
        mae=mae,
        median_relative_error=median_relative,
        spearman_rank_correlation=spearman(actual, predicted),
    )


def _series_by_well(
    interval_response: Iterable[IntervalResponse], n_intervals: int
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    liquid: dict[str, list[float]] = {}
    injection: dict[str, list[float]] = {}
    seen: set[tuple[int, str]] = set()
    for row in interval_response:
        if row.control_step >= n_intervals:
            continue
        key = (row.control_step, row.well)
        if key in seen:
            raise CrmError(
                f"дубликат IntervalResponse на (control_step={row.control_step}, "
                f"well={row.well!r})"
            )
        seen.add(key)
        liquid.setdefault(row.well, [0.0] * n_intervals)[row.control_step] = (
            row.liquid_volume_delta
        )
        injection.setdefault(row.well, [0.0] * n_intervals)[row.control_step] = (
            row.injection_volume_delta
        )
    if not liquid:
        raise CrmError("IntervalResponse пуст: базовую линию не на чем строить")
    return liquid, injection


class CrmBaseline:
    """Подгонка CRM на настоящем отклике и честный замер на отложенной части."""

    def __init__(
        self,
        *,
        tau_intervals: float = DEFAULT_TAU_INTERVALS,
        ridge: float = DEFAULT_RIDGE,
        enforce_material_balance: bool = True,
    ) -> None:
        if tau_intervals < _MIN_TAU:
            raise CrmError(f"tau_intervals={tau_intervals} слишком мала")
        if ridge < 0.0:
            raise CrmError(f"ridge={ridge} отрицателен")
        self.tau_intervals = tau_intervals
        self.ridge = ridge
        self.enforce_material_balance = enforce_material_balance

    def fit(
        self,
        interval_response: Iterable[IntervalResponse],
        *,
        train_intervals: int | None = None,
        n_intervals: int = N_INTERVALS,
    ) -> CrmEvaluation:
        liquid, injection = _series_by_well(interval_response, n_intervals)
        if train_intervals is None:
            train_intervals = int(n_intervals * DEFAULT_TRAIN_FRACTION)
        split = CrmSplit(train_intervals=train_intervals, n_intervals=n_intervals)

        producers = tuple(
            well
            for well in sorted(liquid)
            if all(liquid[well][k] > 0.0 for k in range(n_intervals))
        )
        if not producers:
            raise CrmError(
                "нет ни одной добывающей, работающей все интервалы: честный "
                "разрез по времени невозможен"
            )
        injectors = tuple(
            well
            for well in sorted(injection)
            if sum(injection[well][k] for k in split.train_steps) > 0.0
        )
        if not injectors:
            raise CrmError("нет ни одной нагнетательной с закачкой на обучающей части")

        filtered = {
            well: _filtered(injection[well], self.tau_intervals) for well in injectors
        }
        design = [
            [1.0] + [filtered[well][k] for well in injectors] for k in range(n_intervals)
        ]
        allocation, base = self._solve(
            producers, injectors, liquid, design, split
        )

        model = CrmModel(
            producers=producers,
            injectors=injectors,
            allocation=allocation,
            base_liquid=base,
            tau_intervals=self.tau_intervals,
            split=split,
            material_balance_enforced=self.enforce_material_balance,
        )
        return CrmEvaluation(
            model=model,
            holdout=self._score(model, liquid, design, split.holdout_steps),
            train=self._score(model, liquid, design, split.train_steps),
        )

    def _solve(
        self,
        producers: Sequence[str],
        injectors: Sequence[str],
        liquid: Mapping[str, Sequence[float]],
        design: Sequence[Sequence[float]],
        split: CrmSplit,
    ) -> tuple[tuple[tuple[float, ...], ...], tuple[float, ...]]:
        width = len(injectors) + 1
        normal: dict[str, tuple[list[list[float]], list[float]]] = {}
        for producer in producers:
            gram = [[0.0] * width for _ in range(width)]
            moment = [0.0] * width
            target = liquid[producer]
            for k in split.train_steps:
                row = design[k]
                observed = target[k]
                for a in range(width):
                    value = row[a]
                    if value == 0.0:
                        continue
                    moment[a] += value * observed
                    for b in range(width):
                        gram[a][b] += value * row[b]
            normal[producer] = (gram, moment)

        coefficients = {
            producer: [
                sum(liquid[producer][k] for k in split.train_steps) / split.train_intervals
            ]
            + [0.0] * len(injectors)
            for producer in producers
        }

        for _ in range(_MAX_SWEEPS):
            shift = 0.0
            for producer in producers:
                gram, moment = normal[producer]
                current = coefficients[producer]
                for a in range(width):
                    diagonal = gram[a][a] + (self.ridge if a > 0 else 0.0)
                    if diagonal <= 0.0:
                        continue
                    residual = moment[a] - sum(
                        gram[a][b] * current[b] for b in range(width) if b != a
                    )
                    value = residual / diagonal
                    if value < 0.0:
                        value = 0.0
                    shift = max(shift, abs(value - current[a]))
                    current[a] = value
            if self.enforce_material_balance:
                for column in range(1, width):
                    total = sum(coefficients[p][column] for p in producers)
                    if total > 1.0:
                        for producer in producers:
                            coefficients[producer][column] /= total
            if shift < _CONVERGENCE_TOLERANCE:
                break

        allocation = tuple(
            tuple(coefficients[producer][1:]) for producer in producers
        )
        base = tuple(coefficients[producer][0] for producer in producers)
        return allocation, base

    @staticmethod
    def _score(
        model: CrmModel,
        liquid: Mapping[str, Sequence[float]],
        design: Sequence[Sequence[float]],
        steps: range,
    ) -> CrmMetrics:
        actual: list[float] = []
        predicted: list[float] = []
        for index, producer in enumerate(model.producers):
            row = model.allocation[index]
            intercept = model.base_liquid[index]
            for k in steps:
                actual.append(liquid[producer][k])
                predicted.append(
                    intercept
                    + sum(
                        coefficient * design[k][1 + column]
                        for column, coefficient in enumerate(row)
                    )
                )
        return _metrics(actual, predicted)


def predict_liquid(
    model: CrmModel, injection_by_well: Mapping[str, Sequence[float]], n_intervals: int
) -> dict[str, tuple[float, ...]]:
    """Прогноз помесячных объёмов жидкости под произвольную программу закачки."""

    missing = [well for well in model.injectors if well not in injection_by_well]
    if missing:
        raise CrmError(f"нет программы закачки для нагнетательных: {sorted(missing)}")
    filtered = {
        well: _filtered(tuple(injection_by_well[well][:n_intervals]), model.tau_intervals)
        for well in model.injectors
    }
    result: dict[str, tuple[float, ...]] = {}
    for index, producer in enumerate(model.producers):
        row = model.allocation[index]
        intercept = model.base_liquid[index]
        result[producer] = tuple(
            intercept
            + sum(
                coefficient * filtered[well][k]
                for coefficient, well in zip(row, model.injectors)
            )
            for k in range(n_intervals)
        )
    return result


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """Сравнение суррогата с базовой линией на одних и тех же метриках."""

    baseline: CrmMetrics
    candidate: CrmMetrics
    beats_baseline: bool
    rank_correlation_gain: float


def compare_to_baseline(
    baseline: CrmMetrics, candidate: CrmMetrics
) -> BaselineComparison:
    """§5.5: модель обязана бить CRM по ранговой корреляции, иначе отвергается."""

    if baseline.n_points != candidate.n_points:
        raise CrmError(
            "сравнение с базовой линией требует одной и той же выборки: "
            f"{baseline.n_points} против {candidate.n_points}"
        )
    gain = (
        candidate.spearman_rank_correlation - baseline.spearman_rank_correlation
    )
    return BaselineComparison(
        baseline=baseline,
        candidate=candidate,
        beats_baseline=gain > 0.0,
        rank_correlation_gain=gain,
    )
