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
from typing import Callable, Iterable, MutableMapping, Sequence

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
# прогонов таких интервалов 4201 из 16.9 млн (0.025%), худший -15.84 т, и
# только по массе нефти: жидкость и закачка отрицательными не становятся
# нигде.
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
# на сборке тензоров — замеренная доля 0.025%, и порог в 40 раз выше неё.
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
        return self.body(torch.cat((numeric, embedded), dim=1))


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


def _features(
    item: SurrogateInput,
    wells: tuple[str, ...],
) -> tuple[Tensor, Tensor]:
    _validate_input(item)
    if item.wells != wells:
        raise SurrogateModelError(f"ось wells разошлась: {item.wells} != {wells}")
    well_to_index = {well: index for index, well in enumerate(wells)}
    x = torch.tensor([_node_vector(node) for node in item.nodes], dtype=torch.float32)
    well_index = torch.tensor(
        [well_to_index[node.well] for node in item.nodes], dtype=torch.long
    )
    return x, well_index


def _targets(
    example: TrainingExample,
    stats: MutableMapping[str, int] | None = None,
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
        rows.append([math.log1p(max(0.0, float(value))) for value in raw.values()])
    return torch.tensor(rows, dtype=torch.float32)


def _example_tensors(
    examples: Sequence[TrainingExample],
    wells: tuple[str, ...],
    stats: MutableMapping[str, int] | None = None,
) -> tuple[Tensor, Tensor, Tensor]:
    xs: list[Tensor] = []
    indices: list[Tensor] = []
    ys: list[Tensor] = []
    counters: dict[str, int] = {}
    for example in examples:
        x, well_index = _features(example.input, wells)
        xs.append(x)
        indices.append(well_index)
        ys.append(_targets(example, counters))
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


def _loss_on_loader(
    network: _NodeNetwork,
    loader: DataLoader,
    device: torch.device,
) -> float:
    network.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for x, well_index, y in loader:
            x = x.to(device)
            well_index = well_index.to(device)
            y = y.to(device)
            loss = torch.nn.functional.smooth_l1_loss(
                network(x, well_index), y, reduction="sum"
            )
            total += float(loss.item())
            count += y.numel()
    return total / max(1, count)


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
        x, _, y = _example_tensors(examples, wells)
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
        train_x, train_wells, train_y = _example_tensors(train, model.wells, target_stats)
        val_x, val_wells, val_y = _example_tensors(validation, model.wells)
        train_x = model.input_scaler.transform(train_x)
        val_x = model.input_scaler.transform(val_x)
        train_y = model.target_scaler.transform(train_y)
        val_y = model.target_scaler.transform(val_y)

        generator = torch.Generator().manual_seed(settings.seed)
        train_loader = DataLoader(
            TensorDataset(train_x, train_wells, train_y),
            batch_size=settings.batch_size,
            shuffle=True,
            generator=generator,
        )
        validation_loader = DataLoader(
            TensorDataset(val_x, val_wells, val_y),
            batch_size=settings.batch_size,
            shuffle=False,
        )
        optimizer = torch.optim.AdamW(
            network.parameters(),
            lr=settings.learning_rate,
            weight_decay=settings.weight_decay,
        )

        best_loss = math.inf
        best_state: dict[str, Tensor] | None = None
        best_epoch = 0
        stale = 0
        history: list[EpochMetrics] = []
        for epoch in range(1, settings.max_epochs + 1):
            network.train()
            total = 0.0
            count = 0
            for x, well_index, y in train_loader:
                x = x.to(selected_device)
                well_index = well_index.to(selected_device)
                y = y.to(selected_device)
                optimizer.zero_grad(set_to_none=True)
                prediction = network(x, well_index)
                loss = torch.nn.functional.smooth_l1_loss(prediction, y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), max_norm=5.0)
                optimizer.step()
                total += float(loss.item()) * y.numel()
                count += y.numel()
            train_loss = total / max(1, count)
            validation_loss = _loss_on_loader(network, validation_loader, selected_device)
            epoch_metrics = EpochMetrics(epoch, train_loss, validation_loss)
            history.append(epoch_metrics)
            if epoch_callback is not None:
                epoch_callback(epoch_metrics)
            if validation_loss < best_loss - 1e-6:
                best_loss = validation_loss
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
        x, well_index = _features(candidate, self.wells)
        x = self.input_scaler.transform(x)
        self.network.eval()
        chunks: list[Tensor] = []
        with torch.no_grad():
            for start in range(0, len(x), self.config.batch_size):
                stop = start + self.config.batch_size
                chunks.append(self.network(x[start:stop], well_index[start:stop]))
        standardized = torch.cat(chunks)
        decoded = torch.expm1(self.target_scaler.inverse(standardized)).clamp_min(0.0)

        nodes: list[RawWellStepPrediction] = []
        for source, values in zip(candidate.nodes, decoded.tolist()):
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

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        metadata = {
            "format": self.CHECKPOINT_FORMAT,
            "config": asdict(self.config),
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
        if model._fingerprint() != model.version:
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
