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
    _features,
)

from backend.contexts.surrogate.domain.network import (
    _NodeNetwork,
)

from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
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

from backend.core.contracts import (
    Availability,
    OperatingStatus,
    Role,
)

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


# Контракт (docs/context/08_contracts.md §5, 07_concept.md §5.1) требует
# предсказывать раздельно факт добычи жидкости, обводнённость и приёмистость,
# а нефть выводить как q_ж × (1 − обводнённость). Реализация задачи 34 вместо
# этого предсказывала oil_mass_delta напрямую — то есть шестым независимым
# таргетом ту величину, на которой висит 97% денег, и без связи с жидкостью.


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


# False — без сводки, True/"mean" — средние, "rich" — плюс разброс, крайние
# значения и раздельные средние по добывающим и нагнетательным.


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
_INFERENCE_BATCH_SIZE = 65_536


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
        train_npv_rub: Tensor | None = None,
        validation_npv_rub: Tensor | None = None,
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
        if (train_npv_rub is None) != (validation_npv_rub is None):
            raise SurrogateModelError("точные ранговые цели нужны и для train, и для validation")
        for name, values, counts in (
            ("train", train_npv_rub, train_node_counts),
            ("validation", validation_npv_rub, validation_node_counts),
        ):
            if values is not None and (
                counts is None or values.shape != (len(counts),)
                or not bool(torch.isfinite(values).all())
            ):
                raise SurrogateModelError(f"{name}: неверная ось или нечисловая метка ЧДД")
        if ranking and not settings.money_rub_per_unit:
            raise SurrogateModelError("ранговый лосс требует денежные коэффициенты")
        if ranking and not train_node_counts:
            raise SurrogateModelError(
                "ranking_loss_weight требует train_node_counts: без разбиения по "
                "сценариям попарное сравнение не собрать"
            )
        if ranking:
            step_column = len(_NUMERIC_NAMES) + len(model.static_feature_names)
            size = train_node_counts[0]
            if any(count <= 0 for count in train_node_counts) or sum(train_node_counts) != len(train_x) or len(set(train_node_counts)) != 1:
                raise SurrogateModelError("ранговое обучение требует одинаковые полные оси сценариев")
            for start in range(size, len(train_x), size):
                if (
                    not torch.equal(train_wells[start:start + size], train_wells[:size])
                    or not torch.equal(train_x[start:start + size, step_column], train_x[:size, step_column])
                ):
                    raise SurrogateModelError("порядок well/step разошёлся между сценариями рангового батча")
        train_loader = (
            _ScenarioBatches(
                (train_x, train_wells, train_y),
                train_node_counts,
                scenarios_per_batch=settings.ranking_scenarios_per_batch,
                nodes_per_scenario=settings.ranking_nodes_per_scenario,
                generator=generator,
                scenario_targets=train_npv_rub,
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
                    x, well_index, y, groups, n_groups = batch[:5]
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
                    # Shared coordinates reduce composition noise. Exact
                    # full-scenario labels, when provided, determine the order.
                    money = torch.zeros(
                        n_groups, dtype=prediction.dtype, device=prediction.device
                    )
                    truth = torch.zeros_like(money)
                    money.index_add_(0, groups, _proxy_value(
                        prediction, target_scale, target_mean, rub_per_unit,
                        settings))
                    truth.index_add_(0, groups, _proxy_value(
                        y, target_scale, target_mean, rub_per_unit, settings))
                    if train_npv_rub is not None:
                        truth = batch[5].to(device=selected_device, dtype=prediction.dtype)
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
                scenario_targets=validation_npv_rub,
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
        return predict_with_score(self._predict_output(candidate), candidate, self.domain)

    def _predict_output(self, candidate: SurrogateInput) -> RawModelOutput:
        """Physical prediction without OOD scoring for ensemble orchestration."""

        if candidate.static_feature_names != self.static_feature_names:
            raise SurrogateModelError("статика кандидата не совпадает с checkpoint")
        x, well_index = _features(
            candidate, self.wells, scenario_context=self.config.scenario_context
        )
        return self._predict_output_from_features(candidate, x, well_index)

    def _predict_output_from_features(
        self, candidate: SurrogateInput, x: Tensor, well_index: Tensor
    ) -> RawModelOutput:
        """Decode an already featureized candidate (shared by an ensemble)."""

        if candidate.static_feature_names != self.static_feature_names:
            raise SurrogateModelError("статика кандидата не совпадает с checkpoint")
        x = self.input_scaler.transform(x)
        self.network.eval()
        chunks: list[Tensor] = []
        with torch.no_grad():
            # Training batch size is an optimization hyperparameter, not an
            # inference contract. A complete Model Z scenario has about 23k
            # rows; replaying it in tiny training batches made every
            # fixed-point evaluation needlessly expensive. The network uses
            # row-local LayerNorm, so larger inference batches are equivalent.
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
                # Нефть выводится тождеством контракта, а не предсказывается:
                # это гарантирует согласованность с жидкостью по построению.
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
        with _legacy_checkpoint_modules():
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


