"""Trainable full-trajectory reservoir surrogate (task 34).

The model consumes :class:`surrogate.features.SurrogateInput`, so no
simulator-derived value can leak into inference.  Each ``(well, step)`` node
is mapped to the six raw channels required by :class:`ResponseAdapter`.
History is represented by the cumulative target features and the measured
lambda aggregates produced by ``ScheduleFeatureizer``; a learned well
embedding captures stable per-well effects.

PyTorch is an optional dependency.  Keeping this module out of
``surrogate.__init__`` lets the deterministic core of AIOS run without the
heavy ML stack; install ``aios[ml]`` to train or load a checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableMapping, Sequence

import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader, TensorDataset

from contracts import (
    Availability,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    Role,
)

from .features import SurrogateInput, WellStepFeatures
from .ood import ScoredPrediction, TrainingDomain, fit_domain, predict_with_score
from .raw_model_output import RawModelOutput, RawWellStepPrediction

TARGET_NAMES: tuple[str, ...] = (
    "oil_mass_delta",
    "liquid_volume_delta",
    "injection_volume_delta",
    "liquid_rate",
    "injection_rate",
    "bhp",
)

# Контракт (docs/context/08_contracts.md §5, 07_concept.md §5.1) требует
# предсказывать раздельно факт добычи жидкости, обводнённость и приёмистость,
# а нефть выводить как q_ж × (1 − обводнённость). Реализация задачи 34 вместо
# этого предсказывала oil_mass_delta напрямую — то есть шестым независимым
# таргетом ту величину, на которой висит 97% денег, и без связи с жидкостью.
TARGET_PARAMETERIZATIONS: tuple[str, ...] = ("absolute", "watercut")
WATERCUT_TARGET_NAMES: tuple[str, ...] = (
    "liquid_volume_delta",
    "watercut",
    "injection_volume_delta",
    "liquid_rate",
    "injection_rate",
    "bhp",
)
# Обводнённость выше единицы означала бы отрицательную добычу. В измеренных
# целях такое встречается — это перетоки, артефакт разбора UNSMRY, — но ни
# предсказывать, ни оценивать их нельзя: контракт отрицательную нефть отвергает.
# Потолок 1.5 в денежном прокси оказался дырой, которую ранговый лосс нашёл и
# использовал: поднять сценарий в порядке можно было, загнав обводнённость за
# единицу, и обученная так модель дала Spearman −0.512 при ранге 0.908 на
# валидации. Предел один и тот же во всех путях.
_WATERCUT_CEILING = 1.0

# False — без сводки, True/"mean" — средние, "rich" — плюс разброс, крайние
# значения и раздельные средние по добывающим и нагнетательным.
_SCENARIO_CONTEXTS: tuple[object, ...] = (False, True, "mean", "rich")
_LOSSES: tuple[str, ...] = ("smooth_l1", "mse", "huber")
_LR_SCHEDULES: tuple[str, ...] = ("none", "cosine")
_SELECTION_CRITERIA: tuple[str, ...] = ("loss", "money", "rank")

# Приросты накопленных величин, восстановленные из UNSMRY, могут уйти в минус
# по двум разным причинам, и смешивать их нельзя.
#
# Первая — представление: UNSMRY хранит накопления 4-байтными float, вычитание
# двух близких значений даёт хвост порядка 1e-7 от самого накопления.
#
# Вторая — физика. Масса нефти собирается из COPT по подключениям, а у почти
# остановленной скважины подключения могут работать в обратную сторону: замер
# на прогоне `20260817T104426-70e8e055e519`, скважина 44, интервал 219 —
# `oil_rate = -0.1177` т/сут при `liquid_rate = 0.65` м³/сут, отрицательный
# COPR у 10 из 14 подключений, накопление падает на 3.53 т. Это переток нефти
# обратно в пласт, и OPM сообщает о нём честно. По всему датасету из 732
# прогонов таких интервалов 502 из 16 150 400 (0.0031%), худший -15.84 т, и
# только по массе нефти: жидкость и закачка отрицательными не становятся
# нигде. Считать долю нужно с SMSPEC каждого прогона: один общий индекс
# колонок на весь датасет даёт неверные значения.
#
# Переток — не добыча, поэтому целью берётся ноль. Эталонный расчётчик такую
# строку выбрасывает из экономики целиком (`is_excluded_by_negative_rule`,
# contracts/response.py), то есть её вклад в ЧДД тоже нулевой; предсказать
# отрицательный прирост модель всё равно не может, потому что выход идёт через
# `log1p`/`expm1` и неотрицателен по построению.
#
# Глушить любой минус нельзя, иначе исчезает защита от настоящей ошибки
# в разборе UNSMRY. Поэтому защит две: ниже `_BACKFLOW_FLOOR` обучение падает
# сразу, а если доля таких интервалов превысит `_BACKFLOW_SHARE_LIMIT`, падает
# на сборке тензоров — замеренная доля 0.0031%, порог в 320 раз выше неё.
_ROUNDOFF_TOLERANCE = 1e-3
_BACKFLOW_FIELDS = frozenset({"oil_mass_delta"})
_BACKFLOW_FLOOR = -1e3  # т за месяц; крупнее — это не переток, а баг
_BACKFLOW_SHARE_LIMIT = 0.01

_NUMERIC_NAMES: tuple[str, ...] = (
    "setpoint_m3_per_day",
    "effective_target_rate_m3_per_day",
    "cumulative_target_liquid_m3",
    "cumulative_target_injection_m3",
    "cumulative_neighbor_injection_m3",
    "current_neighbor_injection_m3_per_day",
    "event_count",
    "fixed_event_count",
)


class SurrogateModelError(ValueError):
    """Training data, checkpoint, or candidate axes are inconsistent."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    hidden_width: int = 128
    hidden_layers: int = 3
    well_embedding_dim: int = 16
    dropout: float = 0.05
    learning_rate: float = 2e-3
    weight_decay: float = 1e-5
    batch_size: int = 32_768
    max_epochs: int = 80
    patience: int = 10
    seed: int = 20260816
    # Денежная цена ошибки, ₽ на физическую единицу, в порядке TARGET_NAMES
    # и со знаком (выручка положительна, opex отрицателен). Пустой кортеж
    # отключает денежное взвешивание и возвращает равномерный smooth_l1.
    # Значения обязан подать вызывающий из NormativeSet: ни один компонент
    # не читает норматив мимо конфига (база знаний §11.1).
    money_rub_per_unit: tuple[float, ...] = ()
    money_weight_alpha: float = 0.7
    money_weight_cap: float = 50.0
    # Косинусное затухание и отбор по рангу проверены факторным
    # экспериментом и отклонены: первое ухудшает сжатие разброса
    # (недообученной сети нужно больше шагов, а не меньше), второй
    # выбирает ту же эпоху, что и отбор по лоссу.
    lr_schedule: str = "none"
    select_by: str = "loss"
    target_parameterization: str = "absolute"
    oil_density_t_per_m3: float = 0.9131
    loss: str = "smooth_l1"
    huber_delta: float = 0.1
    residual: bool = False
    scenario_context: object = False
    ranking_loss_weight: float = 0.0
    ranking_top_weighted: bool = False
    ranking_scenarios_per_batch: int = 48
    # Полный сценарий — 23 072 узла; подвыборка ускоряет эпоху, но слишком
    # малая оставляет её без данных: при 640 узлах эпоха видела 2.8% выборки.
    ranking_nodes_per_scenario: int = 4096

    def __post_init__(self) -> None:
        if self.hidden_width < 1 or self.hidden_layers < 1:
            raise SurrogateModelError("hidden_width/hidden_layers должны быть положительными")
        if self.well_embedding_dim < 1:
            raise SurrogateModelError("well_embedding_dim должен быть положительным")
        if not (0.0 <= self.dropout < 1.0):
            raise SurrogateModelError("dropout должен лежать в [0, 1)")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise SurrogateModelError("learning_rate/weight_decay заданы неверно")
        if self.batch_size < 1 or self.max_epochs < 1 or self.patience < 1:
            raise SurrogateModelError("batch_size/max_epochs/patience должны быть положительными")
        object.__setattr__(self, "money_rub_per_unit", tuple(self.money_rub_per_unit))
        if self.money_rub_per_unit and len(self.money_rub_per_unit) != len(TARGET_NAMES):
            raise SurrogateModelError(
                f"money_rub_per_unit должен покрывать все {len(TARGET_NAMES)} целей"
            )
        if any(not math.isfinite(value) for value in self.money_rub_per_unit):
            raise SurrogateModelError("money_rub_per_unit содержит нечисловой коэффициент")
        if not 0.0 <= self.money_weight_alpha <= 1.0:
            raise SurrogateModelError("money_weight_alpha должен лежать в [0, 1]")
        if self.money_weight_cap < 1.0:
            raise SurrogateModelError("money_weight_cap должен быть не меньше 1")
        if self.lr_schedule not in _LR_SCHEDULES:
            raise SurrogateModelError(f"lr_schedule: {' или '.join(_LR_SCHEDULES)}")
        if self.select_by not in _SELECTION_CRITERIA:
            raise SurrogateModelError(f"select_by: {', '.join(_SELECTION_CRITERIA)}")
        if self.target_parameterization not in TARGET_PARAMETERIZATIONS:
            raise SurrogateModelError(
                f"target_parameterization: {' или '.join(TARGET_PARAMETERIZATIONS)}"
            )
        if not self.oil_density_t_per_m3 > 0.0:
            raise SurrogateModelError("oil_density_t_per_m3 должна быть положительной")
        if self.loss not in _LOSSES:
            raise SurrogateModelError(f"loss: {', '.join(_LOSSES)}")
        if self.scenario_context not in _SCENARIO_CONTEXTS:
            raise SurrogateModelError(
                "scenario_context: False, True, 'mean' или 'rich'"
            )
        if self.ranking_loss_weight < 0.0:
            raise SurrogateModelError("ranking_loss_weight не может быть отрицательным")
        if self.ranking_scenarios_per_batch < 2:
            raise SurrogateModelError(
                "ranking_scenarios_per_batch должен быть не меньше двух: "
                "попарное сравнение требует пары"
            )
        if self.ranking_nodes_per_scenario < 1:
            raise SurrogateModelError(
                "ranking_nodes_per_scenario должен быть положительным"
            )
        if not self.huber_delta > 0.0:
            raise SurrogateModelError("huber_delta должна быть положительной")


@dataclass(frozen=True, slots=True)
class Standardizer:
    mean: tuple[float, ...]
    scale: tuple[float, ...]

    @classmethod
    def fit(cls, values: Tensor) -> "Standardizer":
        if values.ndim != 2 or values.shape[0] == 0:
            raise SurrogateModelError("standardizer требует непустую матрицу")
        mean = values.mean(dim=0)
        scale = values.std(dim=0, unbiased=False)
        scale = torch.where(scale > 1e-8, scale, torch.ones_like(scale))
        return cls(tuple(mean.tolist()), tuple(scale.tolist()))

    def transform(self, values: Tensor) -> Tensor:
        mean = torch.tensor(self.mean, dtype=values.dtype, device=values.device)
        scale = torch.tensor(self.scale, dtype=values.dtype, device=values.device)
        return (values - mean) / scale

    def inverse(self, values: Tensor) -> Tensor:
        mean = torch.tensor(self.mean, dtype=values.dtype, device=values.device)
        scale = torch.tensor(self.scale, dtype=values.dtype, device=values.device)
        return values * scale + mean


@dataclass(frozen=True, slots=True)
class TrainingExample:
    input: SurrogateInput
    response: ResponseArtifact


@dataclass(frozen=True, slots=True)
class EpochMetrics:
    epoch: int
    train_loss: float
    validation_loss: float
    # Денежно-взвешенный валидационный лосс и ранговая корреляция сценарного
    # денежного прокси. Нули означают, что взвешивание было отключено.
    validation_money_loss: float = 0.0
    validation_rank: float = 0.0
    learning_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: "TrajectorySurrogate"
    history: tuple[EpochMetrics, ...]
    best_epoch: int
    dataset_hash: str
    backflow_intervals: int = 0
    backflow_worst_tonnes: float = 0.0
    target_rows: int = 0


class _NodeNetwork(nn.Module):
    def __init__(
        self,
        numeric_width: int,
        n_wells: int,
        config: ModelConfig,
    ) -> None:
        super().__init__()
        self.well_embedding = nn.Embedding(n_wells, config.well_embedding_dim)
        width = numeric_width + config.well_embedding_dim
        self.residual = config.residual
        if self.residual:
            # Остаточные блоки одинаковой ширины: градиент доходит до первых
            # слоёв без затухания, поэтому глубина перестаёт мешать обучению.
            self.stem = nn.Linear(width, config.hidden_width)
            self.blocks = nn.ModuleList(
                nn.Sequential(
                    nn.LayerNorm(config.hidden_width),
                    nn.Linear(config.hidden_width, config.hidden_width),
                    nn.SiLU(),
                    nn.Dropout(config.dropout),
                    nn.Linear(config.hidden_width, config.hidden_width),
                )
                for _ in range(config.hidden_layers)
            )
            self.head = nn.Sequential(
                nn.LayerNorm(config.hidden_width),
                nn.Linear(config.hidden_width, len(TARGET_NAMES)),
            )
            self.body = None
            return
        layers: list[nn.Module] = []
        for _ in range(config.hidden_layers):
            layers.extend(
                (
                    nn.Linear(width, config.hidden_width),
                    nn.SiLU(),
                    nn.LayerNorm(config.hidden_width),
                    nn.Dropout(config.dropout),
                )
            )
            width = config.hidden_width
        layers.append(nn.Linear(width, len(TARGET_NAMES)))
        self.body = nn.Sequential(*layers)

    def forward(self, numeric: Tensor, well_index: Tensor) -> Tensor:
        embedded = self.well_embedding(well_index)
        features = torch.cat((numeric, embedded), dim=1)
        if not self.residual:
            return self.body(features)
        hidden = self.stem(features)
        for block in self.blocks:
            hidden = hidden + block(hidden)
        return self.head(hidden)


def _one_hot(value: object, members: Sequence[object]) -> list[float]:
    return [1.0 if value is member else 0.0 for member in members]


def _node_vector(node: WellStepFeatures) -> list[float]:
    numeric = [math.log1p(float(getattr(node, name))) for name in _NUMERIC_NAMES]
    static = [float(value) for value in node.static_values]
    fraction = node.control_step / max(1, N_INTERVALS - 1)
    phase = 2.0 * math.pi * fraction
    return [
        *numeric,
        *static,
        fraction,
        math.sin(phase),
        math.cos(phase),
        *_one_hot(node.availability, tuple(Availability)),
        *_one_hot(node.role, tuple(Role)),
        *_one_hot(node.operating_status, tuple(OperatingStatus)),
    ]


def _validate_input(item: SurrogateInput) -> None:
    expected = {(well, step) for well in item.wells for step in range(N_INTERVALS)}
    actual = {(node.well, node.control_step) for node in item.nodes}
    if actual != expected or len(item.nodes) != len(expected):
        raise SurrogateModelError("SurrogateInput не покрывает wells × 224 без дублей")
    if any(len(node.static_values) != len(item.static_feature_names) for node in item.nodes):
        raise SurrogateModelError("static_values не совпадает со static_feature_names")


def _scenario_summary(x: Tensor, item: SurrogateInput, *, mode: object) -> Tensor:
    """Сводка сценария, одинаковая для всех его узлов.

    `mean` — средние по всем узлам. `rich` добавляет разброс, крайние значения
    и раздельные средние по добывающим и нагнетательным: фонд разнороден, и
    среднее по нему смешивает две несравнимые популяции.
    """
    rows = x.shape[0]
    blocks = [x.mean(dim=0, keepdim=True)]
    if mode == "rich":
        blocks.extend((x.std(dim=0, keepdim=True), x.amax(dim=0, keepdim=True)))
        role_index = {role: index for index, role in enumerate(Role)}
        for role in (Role.PROD, Role.INJ):
            mask = torch.tensor(
                [node.role is role for node in item.nodes], dtype=torch.bool
            )
            blocks.append(
                x[mask].mean(dim=0, keepdim=True)
                if bool(mask.any())
                else torch.zeros(1, x.shape[1], dtype=x.dtype)
            )
    summary = torch.cat(blocks, dim=1)
    return torch.nan_to_num(summary).expand(rows, -1)


def _features(
    item: SurrogateInput,
    wells: tuple[str, ...],
    *,
    scenario_context: object = False,
) -> tuple[Tensor, Tensor]:
    """Признаки узлов одного сценария.

    `scenario_context` дописывает к каждому узлу средние по всем узлам его
    сценария. Без этого узел видит свою скважину, свой шаг и двух соседей
    через λ — то есть из двадцати одного признака сценарий различают ровно
    два, оба λ-производные. Обнуление этих двух роняет ранговую корреляцию по
    ЧДД с +0.53 до −0.14, значит модель ранжирует сценарии почти
    исключительно через них. Сводка даёт прямой канал вместо единственного
    косвенного; считается по `item.nodes`, то есть точно по одному сценарию.
    """
    _validate_input(item)
    if item.wells != wells:
        raise SurrogateModelError(f"ось wells разошлась: {item.wells} != {wells}")
    well_to_index = {well: index for index, well in enumerate(wells)}
    x = torch.tensor([_node_vector(node) for node in item.nodes], dtype=torch.float32)
    if scenario_context:
        x = torch.cat((x, _scenario_summary(x, item, mode=scenario_context)), dim=1)
    well_index = torch.tensor(
        [well_to_index[node.well] for node in item.nodes], dtype=torch.long
    )
    return x, well_index


def _watercut_row(
    raw: Mapping[str, float], *, oil_density_t_per_m3: float
) -> list[float]:
    """Контрактный набор целей: нефть не предсказывается, а выводится.

    Обводнённость определена только там, где течёт жидкость; при нулевом
    объёме она произвольна, потому что нефть всё равно восстановится нулём,
    и мы кладём ноль, чтобы не учить сеть шуму на закрытых интервалах.
    """
    liquid = raw["liquid_volume_delta"]
    if liquid > 0.0:
        oil_volume = raw["oil_mass_delta"] / oil_density_t_per_m3
        watercut = 1.0 - oil_volume / liquid
    else:
        watercut = 0.0
    return [
        liquid,
        watercut,
        raw["injection_volume_delta"],
        raw["liquid_rate"],
        raw["injection_rate"],
        raw["bhp"],
    ]


def _targets(
    example: TrainingExample,
    stats: MutableMapping[str, int] | None = None,
    *,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    item = example.input
    interval = {
        (row.well, row.control_step): row for row in example.response.interval_response
    }
    states = {
        (row.well, row.deck_date_index): row for row in example.response.state_at_date
    }
    rows: list[list[float]] = []
    for node in item.nodes:
        try:
            response = interval[(node.well, node.control_step)]
            state = states[(node.well, 147 + node.control_step)]
        except KeyError as error:
            raise SurrogateModelError(
                f"отклик не покрывает ({node.well!r}, {node.control_step})"
            ) from error
        raw = {
            "oil_mass_delta": response.oil_mass_delta,
            "liquid_volume_delta": response.liquid_volume_delta,
            "injection_volume_delta": response.injection_volume_delta,
            "liquid_rate": state.liquid_rate,
            "injection_rate": state.injection_rate,
            "bhp": state.bhp,
        }
        for name, value in raw.items():
            if not math.isfinite(value):
                raise SurrogateModelError(
                    f"нечисловая цель ({node.well!r}, {node.control_step}) "
                    f"{name}={value!r}"
                )
            if value >= -_ROUNDOFF_TOLERANCE:
                continue
            if name not in _BACKFLOW_FIELDS or value < _BACKFLOW_FLOOR:
                raise SurrogateModelError(
                    f"отрицательная цель ({node.well!r}, {node.control_step}) "
                    f"{name}={value!r}"
                )
            if stats is not None:
                stats["backflow_intervals"] = stats.get("backflow_intervals", 0) + 1
                stats["backflow_worst_milli"] = min(
                    stats.get("backflow_worst_milli", 0), int(value * 1000)
                )
        values = (
            _watercut_row(raw, oil_density_t_per_m3=oil_density_t_per_m3)
            if parameterization == "watercut"
            else list(raw.values())
        )
        rows.append([math.log1p(max(0.0, float(value))) for value in values])
    return torch.tensor(rows, dtype=torch.float32)


def _example_tensors(
    examples: Sequence[TrainingExample],
    wells: tuple[str, ...],
    stats: MutableMapping[str, int] | None = None,
    *,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
    scenario_context: bool = False,
) -> tuple[Tensor, Tensor, Tensor]:
    xs: list[Tensor] = []
    indices: list[Tensor] = []
    ys: list[Tensor] = []
    counters: dict[str, int] = {}
    for example in examples:
        x, well_index = _features(
            example.input, wells, scenario_context=scenario_context
        )
        xs.append(x)
        indices.append(well_index)
        ys.append(
            _targets(
                example,
                counters,
                parameterization=parameterization,
                oil_density_t_per_m3=oil_density_t_per_m3,
            )
        )
    if not xs:
        raise SurrogateModelError("обучающая выборка пуста")
    target = torch.cat(ys)
    backflow = counters.get("backflow_intervals", 0)
    share = backflow / max(1, target.shape[0])
    if share > _BACKFLOW_SHARE_LIMIT:
        raise SurrogateModelError(
            f"перетоков {backflow} из {target.shape[0]} интервалов ({share:.3%}) — "
            f"выше порога {_BACKFLOW_SHARE_LIMIT:.1%}; это уже не переток, "
            "а расхождение в разборе отклика"
        )
    if stats is not None:
        stats.update(counters)
        stats["target_rows"] = int(target.shape[0])
    return torch.cat(xs), torch.cat(indices), target


def _elementwise_loss(
    prediction: Tensor, target: Tensor, settings: "ModelConfig"
) -> Tensor:
    """Поэлементная невязка выбранной функцией потерь.

    `smooth_l1` с beta=1 в стандартизованных целях почти везде квадратичен:
    ошибка выше одного стандартного отклонения — редкость. То есть заявленная
    устойчивость к выбросам не работает, и `huber` с малой дельтой даёт другой
    режим, а `mse` — противоположный.
    """
    if settings.loss == "mse":
        return (prediction - target) ** 2
    if settings.loss == "huber":
        return torch.nn.functional.huber_loss(
            prediction, target, reduction="none", delta=settings.huber_delta
        )
    return torch.nn.functional.smooth_l1_loss(prediction, target, reduction="none")


def _money_coefficients(
    physical: Tensor,
    *,
    rub_per_unit: Tensor,
    parameterization: str,
    oil_density_t_per_m3: float,
) -> Tensor:
    """₽ за единицу каждой цели. При контрактной параметризации — не константа.

    `rub_per_unit` всегда задан в физических константах порядка TARGET_NAMES:
    маржа за тонну нефти, opex за м³ жидкости, opex за м³ закачки. Когда нефть
    выводится из жидкости и обводнённости, цена ошибки по жидкости зависит от
    того, сколько в ней нефти, а цена ошибки по обводнённости — от того,
    сколько жидкости прошло. Это прямое дифференцирование build_cell_flows.
    """
    if parameterization != "watercut":
        return rub_per_unit
    liquid = physical[:, 0:1]
    watercut = physical[:, 1:2].clamp(min=0.0, max=_WATERCUT_CEILING)
    oil_margin = rub_per_unit[0]
    opex_liquid = rub_per_unit[1]
    opex_injection = rub_per_unit[2]
    zeros = torch.zeros_like(liquid)
    return torch.cat(
        (
            opex_liquid + (1.0 - watercut) * oil_density_t_per_m3 * oil_margin,
            -liquid * oil_density_t_per_m3 * oil_margin,
            opex_injection.expand_as(liquid),
            zeros,
            zeros,
            zeros,
        ),
        dim=1,
    )


def _money_weights(
    y: Tensor,
    *,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    alpha: float,
    cap: float,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    """Вес элемента лосса, пропорциональный рублёвой цене его ошибки.

    Цели обучаются как log1p и стандартизуются, поэтому ошибка ε в
    пространстве сети отвечает физической ошибке ε·scale·(1+v). Рубль же
    линеен по физической величине: economics/npv.py build_cell_flows
    умножает oil_mass_t, liquid_volume_m3 и injection_volume_m3 на скалярные
    нормативы. Отсюда вес |₽/ед|·scale·(1+v), где (1+v) восстанавливается
    как exp(y·scale + mean).

    Без этого веса равномерный smooth_l1 минимизирует относительную ошибку и
    уравнивает скважину на 1000 т со скважиной на 1 т, хотя в деньгах первая
    стоит в тысячу раз дороже. Ровно отсюда бралось сжатие разброса ЧДД.
    """
    physical = torch.expm1(y * scale + mean).clamp_min(0.0)
    coefficients = _money_coefficients(
        physical,
        rub_per_unit=rub_per_unit,
        parameterization=parameterization,
        oil_density_t_per_m3=oil_density_t_per_m3,
    )
    weight = coefficients.abs() * scale * torch.exp(y * scale + mean)
    average = weight.mean()
    if not bool(torch.isfinite(average)) or float(average) <= 0.0:
        return torch.ones_like(y)
    normalized = (weight / average).clamp(1.0 / cap, cap)
    return alpha * normalized + (1.0 - alpha)


def _ranks(values: Tensor) -> Tensor:
    order = torch.argsort(values)
    ranks = torch.empty_like(values)
    positions = torch.arange(values.numel(), dtype=values.dtype, device=values.device)
    ranks[order] = positions
    return ranks


def _spearman(left: Tensor, right: Tensor) -> float:
    """Ранговая корреляция без scipy; связи игнорируются — суммы непрерывны."""
    if left.numel() < 2:
        return 0.0
    centred_left = _ranks(left) - (left.numel() - 1) / 2.0
    centred_right = _ranks(right) - (right.numel() - 1) / 2.0
    denominator = torch.sqrt(
        (centred_left * centred_left).sum() * (centred_right * centred_right).sum()
    )
    if float(denominator) == 0.0:
        return 0.0
    return float((centred_left * centred_right).sum() / denominator)


def _scenario_money(
    standardized: Tensor,
    scenario_index: Tensor,
    scenario_count: int,
    *,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    """Сценарный денежный прокси: Σ ₽·физическая величина по всем узлам.

    Это не ЧДД — нет дисконтирования, налога, capex ЭЦН и событийных затрат.
    Но именно линейные по объёму статьи дают подавляющую часть разброса ЧДД
    между сценариями, а прокси считается на том же проходе валидации, что и
    лосс, то есть бесплатно. Он нужен только чтобы упорядочить сценарии.
    """
    physical = torch.expm1(standardized * scale + mean).clamp_min(0.0)
    if parameterization == "watercut":
        liquid = physical[:, 0]
        watercut = physical[:, 1].clamp(min=0.0, max=_WATERCUT_CEILING)
        oil = liquid * (1.0 - watercut) * oil_density_t_per_m3
        value = (
            oil * rub_per_unit[0]
            + liquid * rub_per_unit[1]
            + physical[:, 2] * rub_per_unit[2]
        )
    else:
        value = (physical * rub_per_unit).sum(dim=1)
    totals = torch.zeros(scenario_count, dtype=value.dtype, device=value.device)
    totals.index_add_(0, scenario_index, value)
    return totals


class _ScenarioBatches:
    """Батчи, собранные из целых сценариев, а не из перемешанных узлов.

    Ранговый член лосса сравнивает сценарии между собой, поэтому в батче их
    должно быть несколько сразу. Из каждого сценария берётся случайная выборка
    узлов: денежный прокси — сумма по узлам, значит подвыборка даёт его
    несмещённую оценку с точностью до множителя, а множитель для попарного
    сравнения не важен, он одинаков у всех сценариев батча.
    """

    def __init__(
        self,
        tensors: tuple[Tensor, ...],
        counts: Sequence[int],
        *,
        scenarios_per_batch: int,
        nodes_per_scenario: int,
        generator: torch.Generator,
    ) -> None:
        self.tensors = tensors
        self.scenarios_per_batch = scenarios_per_batch
        self.nodes_per_scenario = nodes_per_scenario
        self.generator = generator
        offsets, start = [], 0
        for size in counts:
            offsets.append((start, size))
            start += size
        if start != tensors[0].shape[0]:
            raise SurrogateModelError(
                f"счётчики сценариев дают {start} строк против {tensors[0].shape[0]}"
            )
        self.offsets = offsets

    def __iter__(self):
        order = torch.randperm(len(self.offsets), generator=self.generator)
        for position in range(0, len(order), self.scenarios_per_batch):
            chosen = order[position : position + self.scenarios_per_batch]
            if len(chosen) < 2:
                continue
            rows, groups = [], []
            for group, index in enumerate(chosen.tolist()):
                start, size = self.offsets[index]
                take = min(self.nodes_per_scenario, size)
                picked = torch.randperm(size, generator=self.generator)[:take]
                rows.append(picked + start)
                groups.append(torch.full((take,), group, dtype=torch.long))
            selection = torch.cat(rows)
            yield (
                *(tensor[selection] for tensor in self.tensors),
                torch.cat(groups),
                len(chosen),
            )


def _standardize_scores(values: Tensor) -> Tensor:
    """Нулевое среднее и единичный разброс; вырожденный случай не делит на ноль."""
    centred = values - values.mean()
    scale = torch.sqrt((centred * centred).mean() + 1e-12)
    return centred / scale


def _proxy_value(
    standardized: Tensor,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    settings: "ModelConfig",
) -> Tensor:
    """Денежная ценность каждого узла — то, что суммируется в сценарный прокси."""
    physical = torch.expm1(standardized * scale + mean).clamp_min(0.0)
    if settings.target_parameterization == "watercut":
        liquid = physical[:, 0]
        watercut = physical[:, 1].clamp(min=0.0, max=_WATERCUT_CEILING)
        oil = liquid * (1.0 - watercut) * settings.oil_density_t_per_m3
        return (oil * rub_per_unit[0] + liquid * rub_per_unit[1]
                + physical[:, 2] * rub_per_unit[2])
    return (physical * rub_per_unit).sum(dim=1)


def _pairwise_ranking_loss(
    predicted: Tensor, actual: Tensor, *, top_weighted: bool = False
) -> Tensor:
    """Логистическая попарная невязка порядка сценариев.

    Для каждой пары с различающимся фактом штраф равен softplus от разности,
    взятой со знаком правильного порядка: пара, упорядоченная верно и с
    запасом, не штрафуется, перевёрнутая — линейно по величине ошибки.

    Оценки предварительно приводятся к нулевому среднему и единичному разбросу
    внутри батча. Без этого сравниваются рубли порядка 1e9, softplus от такой
    разности возвращает саму разность, и член в сто миллионов раз перекрывает
    поштатный лосс — при любом весе, отчего веса 0.3, 1 и 3 давали неотличимый
    результат и обучение не шло вовсе.
    """
    predicted = _standardize_scores(predicted)
    difference = predicted.unsqueeze(0) - predicted.unsqueeze(1)
    truth = actual.unsqueeze(0) - actual.unsqueeze(1)
    mask = truth != 0
    if not bool(mask.any()):
        return predicted.sum() * 0.0
    penalty = torch.nn.functional.softplus(
        -difference[mask] * torch.sign(truth[mask])
    )
    if not top_weighted:
        return penalty.mean()
    # Для шортлиста важна верхушка: перепутать сотое место с сто первым стоит
    # ровно ничего, а первое со вторым — весь смысл. Вес пары равен разнице
    # ценностей 1/(1+позиция), как в NDCG: пары с участием лидеров получают
    # на два порядка больший вес, чем пары из хвоста.
    order = torch.argsort(actual, descending=True)
    position = torch.empty_like(actual)
    position[order] = torch.arange(
        actual.numel(), dtype=actual.dtype, device=actual.device
    )
    gain = 1.0 / (1.0 + position)
    weight = (gain.unsqueeze(0) - gain.unsqueeze(1)).abs()[mask]
    total = weight.sum()
    if float(total) <= 0.0:
        return penalty.mean()
    return (penalty * weight).sum() / total


class _Batches:
    """Нарезка батчей срезом вместо DataLoader.

    `DataLoader` поверх `TensorDataset` выбирает элементы батча по одному и
    склеивает их в Python: на батче 32768 это 3.66 с против 0.05 с у среза,
    то есть больше половины эпохи уходило на нарезку, а не на обучение.
    Перестановка берётся из переданного генератора, поэтому порядок остаётся
    воспроизводимым по сиду.
    """

    def __init__(
        self,
        tensors: tuple[Tensor, ...],
        *,
        batch_size: int,
        generator: torch.Generator | None = None,
    ) -> None:
        self.tensors = tensors
        self.batch_size = batch_size
        self.generator = generator
        self.n_rows = tensors[0].shape[0]

    def __iter__(self):
        if self.generator is None:
            for start in range(0, self.n_rows, self.batch_size):
                stop = start + self.batch_size
                yield tuple(tensor[start:stop] for tensor in self.tensors)
            return
        order = torch.randperm(self.n_rows, generator=self.generator)
        for start in range(0, self.n_rows, self.batch_size):
            index = order[start : start + self.batch_size]
            yield tuple(tensor[index] for tensor in self.tensors)


def _loss_on_loader(
    network: _NodeNetwork,
    loader: "_Batches | DataLoader",
    device: torch.device,
) -> float:
    return _validate(network, loader, device).loss


@dataclass(frozen=True, slots=True)
class _ValidationOutcome:
    loss: float
    money_loss: float
    rank: float


def _validate(
    network: _NodeNetwork,
    loader: "_Batches | DataLoader",
    device: torch.device,
    *,
    scale: Tensor | None = None,
    mean: Tensor | None = None,
    rub_per_unit: Tensor | None = None,
    alpha: float = 0.0,
    cap: float = 1.0,
    scenario_index: Tensor | None = None,
    scenario_count: int = 0,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
    settings: "ModelConfig | None" = None,
) -> _ValidationOutcome:
    """Один проход валидации, отдающий все три критерия отбора чекпоинта."""
    network.eval()
    settings = settings or ModelConfig()
    total = 0.0
    money_total = 0.0
    count = 0
    weighted = rub_per_unit is not None and scale is not None and mean is not None
    ranked = weighted and scenario_index is not None and scenario_count > 0
    predicted_chunks: list[Tensor] = []
    actual_chunks: list[Tensor] = []
    with torch.no_grad():
        for x, well_index, y in loader:
            x = x.to(device)
            well_index = well_index.to(device)
            y = y.to(device)
            prediction = network(x, well_index)
            elementwise = _elementwise_loss(prediction, y, settings)
            total += float(elementwise.sum().item())
            if weighted:
                weights = _money_weights(
                    y, scale=scale, mean=mean, rub_per_unit=rub_per_unit,
                    alpha=alpha, cap=cap, parameterization=parameterization,
                    oil_density_t_per_m3=oil_density_t_per_m3,
                )
                money_total += float((elementwise * weights).sum().item())
            if ranked:
                predicted_chunks.append(prediction.cpu())
                actual_chunks.append(y.cpu())
            count += y.numel()
    divisor = max(1, count)
    loss = total / divisor
    money_loss = money_total / divisor if weighted else loss
    rank = 0.0
    if ranked:
        cpu_scale = scale.cpu()
        cpu_mean = mean.cpu()
        cpu_rub = rub_per_unit.cpu()
        predicted_money = _scenario_money(
            torch.cat(predicted_chunks), scenario_index, scenario_count,
            scale=cpu_scale, mean=cpu_mean, rub_per_unit=cpu_rub,
            parameterization=parameterization,
            oil_density_t_per_m3=oil_density_t_per_m3,
        )
        actual_money = _scenario_money(
            torch.cat(actual_chunks), scenario_index, scenario_count,
            scale=cpu_scale, mean=cpu_mean, rub_per_unit=cpu_rub,
            parameterization=parameterization,
            oil_density_t_per_m3=oil_density_t_per_m3,
        )
        rank = _spearman(predicted_money, actual_money)
    return _ValidationOutcome(loss=loss, money_loss=money_loss, rank=rank)


class TrajectorySurrogate:
    """Neural predictor with mandatory OOD score and stable checkpoint id."""

    CHECKPOINT_FORMAT = "aios.surrogate.node-trajectory.v1"

    def __init__(
        self,
        *,
        config: ModelConfig,
        wells: tuple[str, ...],
        static_feature_names: tuple[str, ...],
        input_scaler: Standardizer,
        target_scaler: Standardizer,
        domain: TrainingDomain,
        network: _NodeNetwork,
        dataset_hash: str,
        version: str = "",
    ) -> None:
        self.config = config
        self.wells = wells
        self.static_feature_names = static_feature_names
        self.input_scaler = input_scaler
        self.target_scaler = target_scaler
        self.domain = domain
        self.network = network.cpu().eval()
        self.dataset_hash = dataset_hash
        self.version = version or self._fingerprint()

    @classmethod
    def initialize(
        cls,
        examples: Sequence[TrainingExample],
        *,
        config: ModelConfig | None = None,
        dataset_hash: str = "untrained",
    ) -> "TrajectorySurrogate":
        if not examples:
            raise SurrogateModelError("модель нельзя инициализировать без примеров")
        settings = config or ModelConfig()
        torch.manual_seed(settings.seed)
        wells = examples[0].input.wells
        static_names = examples[0].input.static_feature_names
        x, _, y = _example_tensors(
            examples,
            wells,
            parameterization=settings.target_parameterization,
            oil_density_t_per_m3=settings.oil_density_t_per_m3,
            scenario_context=settings.scenario_context,
        )
        network = _NodeNetwork(x.shape[1], len(wells), settings)
        return cls(
            config=settings,
            wells=wells,
            static_feature_names=static_names,
            input_scaler=Standardizer.fit(x),
            target_scaler=Standardizer.fit(y),
            domain=fit_domain([example.input for example in examples]),
            network=network,
            dataset_hash=dataset_hash,
        )

    @classmethod
    def fit(
        cls,
        train: Sequence[TrainingExample],
        validation: Sequence[TrainingExample],
        *,
        config: ModelConfig | None = None,
        dataset_hash: str,
        device: str | None = None,
        epoch_callback: Callable[[EpochMetrics], None] | None = None,
    ) -> TrainingResult:
        if not train or not validation:
            raise SurrogateModelError("train и validation должны быть непустыми")
        model = cls.initialize(train, config=config, dataset_hash=dataset_hash)
        settings = model.config
        selected_device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        network = model.network.to(selected_device)

        target_stats: dict[str, int] = {}
        parameterization = dict(
            parameterization=settings.target_parameterization,
            oil_density_t_per_m3=settings.oil_density_t_per_m3,
            scenario_context=settings.scenario_context,
        )
        train_x, train_wells, train_y = _example_tensors(
            train, model.wells, target_stats, **parameterization
        )
        val_x, val_wells, val_y = _example_tensors(
            validation, model.wells, **parameterization
        )
        return cls.fit_tensors(
            model,
            train=(
                model.input_scaler.transform(train_x),
                train_wells,
                model.target_scaler.transform(train_y),
            ),
            validation=(
                model.input_scaler.transform(val_x),
                val_wells,
                model.target_scaler.transform(val_y),
            ),
            validation_node_counts=tuple(
                len(item.input.nodes) for item in validation
            ),
            train_node_counts=tuple(len(item.input.nodes) for item in train),
            dataset_hash=dataset_hash,
            device=device,
            epoch_callback=epoch_callback,
            target_stats=target_stats,
        )

    @classmethod
    def fit_tensors(
        cls,
        model: "TrajectorySurrogate",
        *,
        train: tuple[Tensor, Tensor, Tensor],
        validation: tuple[Tensor, Tensor, Tensor],
        validation_node_counts: Sequence[int],
        train_node_counts: Sequence[int] | None = None,
        dataset_hash: str,
        device: str | None = None,
        epoch_callback: Callable[[EpochMetrics], None] | None = None,
        target_stats: MutableMapping[str, int] | None = None,
    ) -> TrainingResult:
        """Обучение по готовым тензорам, без списка `TrainingExample`.

        Нужно там, где примеры не помещаются в память: на 700 прогонах Model_Z
        одни отклики занимают около 15 ГБ (43 млн объектов Python), тогда как
        тензоры тех же данных — 2.8 ГБ. Вызывающий строит тензоры потоком,
        освобождая отклик сразу после каждого сценария, и передаёт сюда только
        их. `fit` остаётся прежним и делегирует сюда же, поэтому расхождения
        между двумя путями обучения быть не может.

        Тензоры целей ожидаются **уже приведёнными** скейлерами модели —
        ровно так, как это делает `fit`.
        """
        settings = model.config
        target_stats = {} if target_stats is None else target_stats
        selected_device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        network = model.network.to(selected_device)
        train_x, train_wells, train_y = train
        val_x, val_wells, val_y = validation
        validation_scenarios = len(validation_node_counts)

        generator = torch.Generator().manual_seed(settings.seed)
        ranking = settings.ranking_loss_weight > 0.0
        if ranking and train_node_counts is None:
            raise SurrogateModelError(
                "ranking_loss_weight требует train_node_counts: без разбиения по "
                "сценариям попарное сравнение не собрать"
            )
        train_loader = (
            _ScenarioBatches(
                (train_x, train_wells, train_y),
                train_node_counts,
                scenarios_per_batch=settings.ranking_scenarios_per_batch,
                nodes_per_scenario=settings.ranking_nodes_per_scenario,
                generator=generator,
            )
            if ranking
            else _Batches(
                (train_x, train_wells, train_y),
                batch_size=settings.batch_size,
                generator=generator,
            )
        )
        validation_loader = _Batches(
            (val_x, val_wells, val_y), batch_size=settings.batch_size
        )
        optimizer = torch.optim.AdamW(
            network.parameters(),
            lr=settings.learning_rate,
            weight_decay=settings.weight_decay,
        )
        scheduler = (
            torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer, T_max=settings.max_epochs
            )
            if settings.lr_schedule == "cosine"
            else None
        )

        # Денежная разметка целей. Пустой money_rub_per_unit оставляет
        # равномерный smooth_l1 и отбор по валидационному лоссу — поведение,
        # которым обучен чекпоинт задачи 34.
        weighted = bool(settings.money_rub_per_unit)
        target_scale = torch.tensor(
            model.target_scaler.scale, dtype=train_y.dtype, device=selected_device
        )
        target_mean = torch.tensor(
            model.target_scaler.mean, dtype=train_y.dtype, device=selected_device
        )
        rub_per_unit = torch.tensor(
            settings.money_rub_per_unit or (0.0,) * len(TARGET_NAMES),
            dtype=train_y.dtype,
            device=selected_device,
        )
        scenario_index = torch.repeat_interleave(
            torch.arange(validation_scenarios),
            torch.tensor(list(validation_node_counts)),
        )
        criterion = settings.select_by if weighted else "loss"

        best_loss = math.inf
        best_state: dict[str, Tensor] | None = None
        best_epoch = 0
        stale = 0
        history: list[EpochMetrics] = []
        for epoch in range(1, settings.max_epochs + 1):
            network.train()
            total = 0.0
            count = 0
            for batch in train_loader:
                if ranking:
                    x, well_index, y, groups, n_groups = batch
                    groups = groups.to(selected_device)
                else:
                    x, well_index, y = batch
                x = x.to(selected_device)
                well_index = well_index.to(selected_device)
                y = y.to(selected_device)
                optimizer.zero_grad(set_to_none=True)
                prediction = network(x, well_index)
                if weighted:
                    elementwise = _elementwise_loss(prediction, y, settings)
                    weights = _money_weights(
                        y,
                        scale=target_scale,
                        mean=target_mean,
                        rub_per_unit=rub_per_unit,
                        alpha=settings.money_weight_alpha,
                        cap=settings.money_weight_cap,
                        parameterization=settings.target_parameterization,
                        oil_density_t_per_m3=settings.oil_density_t_per_m3,
                    )
                    loss = (elementwise * weights).mean()
                else:
                    loss = _elementwise_loss(prediction, y, settings).mean()
                if ranking:
                    # Денежный прокси по подвыборке узлов каждого сценария:
                    # множитель одинаков у всех, поэтому порядок не искажает.
                    money = torch.zeros(
                        n_groups, dtype=prediction.dtype, device=prediction.device
                    )
                    truth = torch.zeros_like(money)
                    money.index_add_(0, groups, _proxy_value(
                        prediction, target_scale, target_mean, rub_per_unit,
                        settings))
                    truth.index_add_(0, groups, _proxy_value(
                        y, target_scale, target_mean, rub_per_unit, settings))
                    loss = loss + settings.ranking_loss_weight * (
                        _pairwise_ranking_loss(
                            money, truth,
                            top_weighted=settings.ranking_top_weighted,
                        )
                    )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), max_norm=5.0)
                optimizer.step()
                total += float(loss.item()) * y.numel()
                count += y.numel()
            train_loss = total / max(1, count)
            outcome = _validate(
                network,
                validation_loader,
                selected_device,
                scale=target_scale if weighted else None,
                mean=target_mean if weighted else None,
                rub_per_unit=rub_per_unit if weighted else None,
                alpha=settings.money_weight_alpha,
                cap=settings.money_weight_cap,
                scenario_index=scenario_index if criterion == "rank" else None,
                scenario_count=validation_scenarios if criterion == "rank" else 0,
                parameterization=settings.target_parameterization,
                oil_density_t_per_m3=settings.oil_density_t_per_m3,
                settings=settings,
            )
            validation_loss = outcome.loss
            current_lr = float(optimizer.param_groups[0]["lr"])
            if scheduler is not None:
                scheduler.step()
            # Критерий отбора — всегда «меньше лучше». Ранговый берётся со
            # знаком минус: суррогат сдаёт порядок сценариев, а не поштатную
            # MSE, и argmin по шумному лоссу выбирал удачную флуктуацию.
            if criterion == "rank":
                score = -outcome.rank
            elif criterion == "money":
                score = outcome.money_loss
            else:
                score = validation_loss
            epoch_metrics = EpochMetrics(
                epoch,
                train_loss,
                validation_loss,
                validation_money_loss=outcome.money_loss,
                validation_rank=outcome.rank,
                learning_rate=current_lr,
            )
            history.append(epoch_metrics)
            if epoch_callback is not None:
                epoch_callback(epoch_metrics)
            if score < best_loss - 1e-6:
                best_loss = score
                best_epoch = epoch
                best_state = {
                    key: value.detach().cpu().clone()
                    for key, value in network.state_dict().items()
                }
                stale = 0
            else:
                stale += 1
                if stale >= settings.patience:
                    break
        if best_state is None:
            raise SurrogateModelError("обучение не дало конечного validation loss")
        network.load_state_dict(best_state)
        model.network = network.cpu().eval()
        model.version = model._fingerprint()
        return TrainingResult(
            model=model,
            history=tuple(history),
            best_epoch=best_epoch,
            dataset_hash=dataset_hash,
            backflow_intervals=target_stats.get("backflow_intervals", 0),
            backflow_worst_tonnes=target_stats.get("backflow_worst_milli", 0) / 1000.0,
            target_rows=target_stats.get("target_rows", 0),
        )

    def predict(self, candidate: SurrogateInput) -> ScoredPrediction:
        if candidate.static_feature_names != self.static_feature_names:
            raise SurrogateModelError("статика кандидата не совпадает с checkpoint")
        x, well_index = _features(
            candidate, self.wells, scenario_context=self.config.scenario_context
        )
        x = self.input_scaler.transform(x)
        self.network.eval()
        chunks: list[Tensor] = []
        with torch.no_grad():
            for start in range(0, len(x), self.config.batch_size):
                stop = start + self.config.batch_size
                chunks.append(self.network(x[start:stop], well_index[start:stop]))
        standardized = torch.cat(chunks)
        decoded = torch.expm1(self.target_scaler.inverse(standardized)).clamp_min(0.0)
        watercut_mode = self.config.target_parameterization == "watercut"

        nodes: list[RawWellStepPrediction] = []
        for source, values in zip(candidate.nodes, decoded.tolist()):
            if watercut_mode:
                # Нефть выводится тождеством контракта, а не предсказывается:
                # это гарантирует согласованность с жидкостью по построению.
                liquid, watercut, injection, liquid_rate, injection_rate, bhp = values
                # Обводнённость выше единицы означала бы отрицательную добычу.
                # В целях такое встречается — это перетоки, измеренный артефакт
                # разбора UNSMRY, — но предсказывать их нельзя: контракт
                # отрицательную нефть отвергает, и ранговый лосс, двигая
                # предсказания свободнее, выводил её за −160 т.
                watercut = min(max(watercut, 0.0), _WATERCUT_CEILING)
                oil = liquid * (1.0 - watercut) * self.config.oil_density_t_per_m3
            else:
                oil, liquid, injection, liquid_rate, injection_rate, bhp = values
            active = (
                source.availability is Availability.AVAILABLE
                and source.operating_status is OperatingStatus.OPEN
            )
            if not active or source.role is Role.NONE:
                oil = liquid = injection = liquid_rate = injection_rate = 0.0
            elif source.role is Role.PROD:
                injection = injection_rate = 0.0
            elif source.role is Role.INJ:
                oil = liquid = liquid_rate = 0.0
            nodes.append(
                RawWellStepPrediction(
                    well=source.well,
                    control_step=source.control_step,
                    oil_mass_delta=oil,
                    liquid_volume_delta=liquid,
                    injection_volume_delta=injection,
                    liquid_rate=liquid_rate,
                    injection_rate=injection_rate,
                    bhp=bhp,
                )
            )
        output = RawModelOutput(
            canonical_schedule_hash=candidate.canonical_schedule_hash,
            wells=candidate.wells,
            nodes=tuple(nodes),
        )
        return predict_with_score(output, candidate, self.domain)

    def _fingerprint(self, config: dict | None = None) -> str:
        """Отпечаток весов и метаданных checkpoint.

        `config` передаётся только при проверке загруженного файла: там
        берётся словарь, записанный при сохранении, а не `asdict` текущего
        `ModelConfig`. Иначе любое новое поле конфига с умолчанием меняет
        отпечаток и объявляет повреждёнными все ранее обученные модели,
        включая `model-task34-700`, на котором держатся G5 и G7.
        """

        digest = hashlib.sha256()
        metadata = {
            "format": self.CHECKPOINT_FORMAT,
            "config": asdict(self.config) if config is None else dict(config),
            "dataset_hash": self.dataset_hash,
            "input_scaler": asdict(self.input_scaler),
            "static_feature_names": self.static_feature_names,
            "target_scaler": asdict(self.target_scaler),
            "wells": self.wells,
        }
        digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        for name, tensor in sorted(self.network.state_dict().items()):
            digest.update(name.encode("utf-8"))
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def save(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "format": self.CHECKPOINT_FORMAT,
                "config": asdict(self.config),
                "dataset_hash": self.dataset_hash,
                "domain": self.domain,
                "input_scaler": asdict(self.input_scaler),
                "network": self.network.state_dict(),
                "static_feature_names": self.static_feature_names,
                "target_scaler": asdict(self.target_scaler),
                "version": self.version,
                "wells": self.wells,
            },
            destination,
        )
        return destination

    @classmethod
    def load(cls, path: Path | str) -> "TrajectorySurrogate":
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("format") != cls.CHECKPOINT_FORMAT:
            raise SurrogateModelError(f"неизвестный формат checkpoint: {payload.get('format')!r}")
        config = ModelConfig(**payload["config"])
        input_scaler = Standardizer(**payload["input_scaler"])
        target_scaler = Standardizer(**payload["target_scaler"])
        wells = tuple(payload["wells"])
        network = _NodeNetwork(len(input_scaler.mean), len(wells), config)
        network.load_state_dict(payload["network"])
        model = cls(
            config=config,
            wells=wells,
            static_feature_names=tuple(payload["static_feature_names"]),
            input_scaler=input_scaler,
            target_scaler=target_scaler,
            domain=payload["domain"],
            network=network,
            dataset_hash=str(payload["dataset_hash"]),
            version=str(payload["version"]),
        )
        if model._fingerprint(payload["config"]) != model.version:
            raise SurrogateModelError("checkpoint повреждён: version не совпадает с весами")
        return model


def split_examples(
    examples: Sequence[TrainingExample],
    *,
    validation_fraction: float = 0.15,
    test_fraction: float = 0.15,
    seed: int = 20260816,
) -> tuple[tuple[TrainingExample, ...], tuple[TrainingExample, ...], tuple[TrainingExample, ...]]:
    """Deterministic scenario-level split; nodes from one run never leak."""

    if not (0.0 < validation_fraction < 1.0 and 0.0 < test_fraction < 1.0):
        raise SurrogateModelError("validation_fraction/test_fraction должны лежать в (0, 1)")
    if validation_fraction + test_fraction >= 1.0:
        raise SurrogateModelError("на train не осталось сценариев")
    if len(examples) < 7:
        raise SurrogateModelError("для train/validation/test нужно хотя бы 7 сценариев")
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(len(examples), generator=generator).tolist()
    n_test = max(1, round(len(examples) * test_fraction))
    n_validation = max(1, round(len(examples) * validation_fraction))
    test_ids = set(order[:n_test])
    validation_ids = set(order[n_test : n_test + n_validation])
    train = tuple(item for index, item in enumerate(examples) if index not in test_ids | validation_ids)
    validation = tuple(item for index, item in enumerate(examples) if index in validation_ids)
    test = tuple(item for index, item in enumerate(examples) if index in test_ids)
    return train, validation, test


def target_mae(
    model: TrajectorySurrogate,
    examples: Iterable[TrainingExample],
) -> dict[str, float]:
    """Real-unit channel MAE for diagnostics; never used as the sole gate."""

    totals = [0.0] * len(TARGET_NAMES)
    count = 0
    for example in examples:
        predicted = model.predict(example.input).output
        actual = torch.expm1(_targets(example))
        estimate = torch.tensor(
            [
                [float(getattr(node, name)) for name in TARGET_NAMES]
                for node in predicted.nodes
            ]
        )
        error = (actual - estimate).abs().sum(dim=0)
        totals = [total + float(value) for total, value in zip(totals, error)]
        count += actual.shape[0]
    if count == 0:
        raise SurrogateModelError("метрики не считаются на пустом наборе")
    return {name: total / count for name, total in zip(TARGET_NAMES, totals)}
