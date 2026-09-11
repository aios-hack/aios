from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
)
from typing import (
    Sequence,
)
import torch
from torch import (
    Tensor,
)


class _ScenarioBatches:
    """Батчи, собранные из целых сценариев, а не из перемешанных узлов.

    Ранговый член лосса сравнивает сценарии между собой, поэтому в батче их
    должно быть несколько сразу. Из каждого сценария берётся случайная выборка
    узлов с одинаковыми координатами во всех сценариях батча. Это снижает
    шум состава фонда при попарном сравнении; несмещённость отдельной суммы
    сама по себе не гарантирует сохранения порядка. Полные метки ЧДД
    передаются отдельно через scenario_targets.
    """

    def __init__(
        self,
        tensors: tuple[Tensor, ...],
        counts: Sequence[int],
        *,
        scenarios_per_batch: int,
        nodes_per_scenario: int,
        generator: torch.Generator,
        scenario_targets: Tensor | None = None,
    ) -> None:
        self.tensors = tensors
        self.scenarios_per_batch = scenarios_per_batch
        self.nodes_per_scenario = nodes_per_scenario
        self.generator = generator
        self.scenario_targets = scenario_targets
        if not counts or any(size <= 0 for size in counts) or len(set(counts)) != 1:
            raise SurrogateModelError("ранговые батчи требуют одинаковые непустые оси сценариев")
        if scenario_targets is not None and (
            scenario_targets.shape != (len(counts),)
            or not bool(torch.isfinite(scenario_targets).all())
        ):
            raise SurrogateModelError("ранговые цели не покрывают сценарии конечными числами")
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
            # Common well/step coordinates remove composition noise between
            # schedules. Independent samples reversed ~34% of train pairs.
            size = self.offsets[0][1]
            take = min(self.nodes_per_scenario, size)
            picked = torch.randperm(size, generator=self.generator)[:take]
            for group, index in enumerate(chosen.tolist()):
                start, size = self.offsets[index]
                rows.append(picked + start)
                groups.append(torch.full((take,), group, dtype=torch.long))
            selection = torch.cat(rows)
            yield (
                *(tensor[selection] for tensor in self.tensors),
                torch.cat(groups),
                len(chosen),
                *((self.scenario_targets[chosen],) if self.scenario_targets is not None else ()),
            )


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
