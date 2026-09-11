
from __future__ import annotations

from backend.contexts.surrogate.domain.model_choices import (
    TARGET_PARAMETERIZATIONS,
    _LOSSES,
    _LR_SCHEDULES,
    _SCENARIO_CONTEXTS,
    _SELECTION_CRITERIA,
)

from backend.contexts.surrogate.application.validation import (
    split_examples,
    target_mae,
)
from backend.contexts.surrogate.domain.losses import (
    _scenario_money,
    _spearman,
)
from backend.contexts.surrogate.domain.vectorize import (
    _targets,
    _watercut_row,
)


from backend.contexts.surrogate.domain.model_types import (
    EpochMetrics,
    ModelConfig,
    Standardizer,
    TARGET_NAMES,
    TrainingExample,
    TrainingResult,
    _NUMERIC_NAMES,
    _WATERCUT_CEILING,
)

from backend.contexts.surrogate.infrastructure.checkpoints import (
    _legacy_checkpoint_modules,
)

from backend.contexts.surrogate.application.validation import (
    _validate,
)

from backend.contexts.surrogate.domain.batches import (
    _Batches,
    _ScenarioBatches,
)

from backend.contexts.surrogate.domain.losses import (
    _elementwise_loss,
    _money_weights,
    _pairwise_ranking_loss,
    _proxy_value,
)

from backend.contexts.surrogate.domain.vectorize import (
    _example_tensors,
    build_features,
)

from backend.contexts.surrogate.domain.network import (
    _NodeNetwork,
)

from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
)

from backend.contexts.surrogate.application.model_training import (
    fit_tensors as _fit_tensors,
)

import hashlib
import json
import math
from dataclasses import (
    asdict,
)
from pathlib import Path
from typing import (
    Callable,
    MutableMapping,
    Sequence,
)

import torch
from torch import (
    Tensor,
)

from backend.contexts.schedule.domain.schedule import Availability, OperatingStatus, Role

from backend.contexts.surrogate.domain.features import (
    SurrogateInput,
)
from backend.contexts.robustness.domain.ood import (
    ScoredPrediction,
    TrainingDomain,
    fit_domain,
    predict_with_score,
)
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)


WATERCUT_TARGET_NAMES: tuple[str, ...] = (
    "liquid_volume_delta",
    "watercut",
    "injection_volume_delta",
    "liquid_rate",
    "injection_rate",
    "bhp",
)


_INFERENCE_BATCH_SIZE = 65_536


class TrajectorySurrogate:
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
            raise SurrogateModelError("the model cannot be initialised without samples")
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
            raise SurrogateModelError("train and validation must be non-empty")
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
        train_npv_rub: Tensor | None = None,
        validation_npv_rub: Tensor | None = None,
    ) -> TrainingResult:
        return _fit_tensors(
            model,
            train=train,
            validation=validation,
            validation_node_counts=validation_node_counts,
            train_node_counts=train_node_counts,
            dataset_hash=dataset_hash,
            device=device,
            epoch_callback=epoch_callback,
            target_stats=target_stats,
            train_npv_rub=train_npv_rub,
            validation_npv_rub=validation_npv_rub,
            batches=_Batches,
            scenario_batches=_ScenarioBatches,
        )

    def predict(self, candidate: SurrogateInput) -> ScoredPrediction:
        return predict_with_score(self._predict_output(candidate), candidate, self.domain)

    def _predict_output(self, candidate: SurrogateInput) -> RawModelOutput:
        if candidate.static_feature_names != self.static_feature_names:
            raise SurrogateModelError("candidate static features do not match the checkpoint")
        x, well_index = build_features(
            candidate, self.wells, scenario_context=self.config.scenario_context
        )
        return self._predict_output_from_features(candidate, x, well_index)

    def _predict_output_from_features(
        self, candidate: SurrogateInput, x: Tensor, well_index: Tensor
    ) -> RawModelOutput:
        if candidate.static_feature_names != self.static_feature_names:
            raise SurrogateModelError("candidate static features do not match the checkpoint")
        x = self.input_scaler.transform(x)
        self.network.eval()
        chunks: list[Tensor] = []
        with torch.no_grad():
            batch_size = max(self.config.batch_size, _INFERENCE_BATCH_SIZE)
            for start in range(0, len(x), batch_size):
                stop = start + batch_size
                chunks.append(self.network(x[start:stop], well_index[start:stop]))
        standardized = torch.cat(chunks)
        decoded = torch.expm1(self.target_scaler.inverse(standardized)).clamp_min(0.0)
        watercut_mode = self.config.target_parameterization == "watercut"

        nodes: list[RawWellStepPrediction] = []
        for source, values in zip(candidate.nodes, decoded.tolist()):
            if watercut_mode:
                liquid, watercut, injection, liquid_rate, injection_rate, bhp = values
                watercut = min(max(watercut, 0.0), _WATERCUT_CEILING)
                oil = liquid * (1.0 - watercut) * self.config.oil_density_t_per_m3
            else:
                oil, liquid, injection, liquid_rate, injection_rate, bhp = values
            oil = min(oil, liquid * self.config.oil_density_t_per_m3)
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
        return RawModelOutput(
            canonical_schedule_hash=candidate.canonical_schedule_hash,
            wells=candidate.wells,
            nodes=tuple(nodes),
        )

    def _fingerprint(self, config: dict | None = None) -> str:
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
        with _legacy_checkpoint_modules():
            payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("format") != cls.CHECKPOINT_FORMAT:
            raise SurrogateModelError(f"unknown checkpoint format: {payload.get('format')!r}")
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
            raise SurrogateModelError("checkpoint is corrupted: version does not match the weights")
        return model


