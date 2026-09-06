"""Тензоры под контрактную параметризацию целей, без повторной ретензоризации.

Контракт требует предсказывать жидкость и обводнённость, а нефть выводить как
`жидкость × (1 − обводнённость)`. Production-чекпоинт обучен в режиме
`absolute`, где нефть — независимый шестой канал, и переход на контрактный
набор считался заблокированным: `tools/surrogate_train_tensors.py` не даёт
менять параметризацию, а `tools/surrogate_retensorize.py` требует сырых чанков
откликов и полного пересчёта.

Пересчёт не нужен. Обводнённость — **чистая функция уже сохранённых целей**:

    watercut = 1 − (oil_mass_delta / плотность) / liquid_volume_delta,
    при liquid_volume_delta = 0 обводнённость равна нулю,

а сами цели лежат в кеше как `log1p(max(0, значение))`. Поэтому достаточно
разложить логарифм, применить ту же формулу, что `model._watercut_row`, и
свернуть обратно. Признаки, оси скважин, сплиты и идентичности переносятся без
изменений: меняется ровно один тензор из трёх.

Порядок каналов на выходе — `WATERCUT_TARGET_NAMES`:
`liquid_volume_delta, watercut, injection_volume_delta, liquid_rate,
injection_rate, bhp`.

Запуск:

    PYTHONPATH=. python tools/surrogate_watercut_tensors.py \\
        --tensors data/lean700/tensors_context_490_canonical.pt \\
        --output data/lean700/tensors_context_490_watercut.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

from surrogate.model import TARGET_NAMES, WATERCUT_TARGET_NAMES, _WATERCUT_CEILING

SOURCE_FORMAT = "aios.surrogate-tensors.v2"
OUTPUT_FORMAT = "aios.surrogate-tensors-watercut.v1"
DEFAULT_OIL_DENSITY = 0.9131

_OIL = TARGET_NAMES.index("oil_mass_delta")
_LIQUID = TARGET_NAMES.index("liquid_volume_delta")
_INJECTION = TARGET_NAMES.index("injection_volume_delta")
_LIQUID_RATE = TARGET_NAMES.index("liquid_rate")
_INJECTION_RATE = TARGET_NAMES.index("injection_rate")
_BHP = TARGET_NAMES.index("bhp")


class WatercutTensorError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oil-density", type=float, default=DEFAULT_OIL_DENSITY)
    return parser


def to_watercut_targets(targets: torch.Tensor, *, oil_density: float) -> torch.Tensor:
    """`log1p` absolute-цели → `log1p` контрактные цели.

    Повторяет `model._watercut_row` и последующий `log1p(max(0, ·))` из
    `model._targets` — включая то, что при нулевой жидкости обводнённость
    кладётся нулём, а не считается: нефть всё равно восстановится нулём, и
    учить сеть шуму на закрытых интервалах незачем.
    """

    if targets.ndim != 2 or targets.shape[1] != len(TARGET_NAMES):
        raise WatercutTensorError(
            f"ожидались цели ширины {len(TARGET_NAMES)}, получено {tuple(targets.shape)}"
        )
    physical = torch.expm1(targets.to(torch.float64))
    liquid = physical[:, _LIQUID]
    oil_volume = physical[:, _OIL] / oil_density
    flowing = liquid > 0.0
    watercut = torch.where(
        flowing,
        1.0 - oil_volume / liquid.clamp_min(1e-12),
        torch.zeros_like(liquid),
    )
    rows = torch.stack(
        (
            liquid,
            watercut,
            physical[:, _INJECTION],
            physical[:, _LIQUID_RATE],
            physical[:, _INJECTION_RATE],
            physical[:, _BHP],
        ),
        dim=1,
    )
    return torch.log1p(rows.clamp_min(0.0)).to(targets.dtype)


def main() -> int:
    args = _parser().parse_args()
    if not args.tensors.exists():
        raise WatercutTensorError(f"тензоры не найдены: {args.tensors}")
    if args.output.exists():
        raise WatercutTensorError(f"отказываюсь перезаписывать: {args.output}")
    if args.oil_density <= 0.0:
        raise WatercutTensorError("плотность нефти должна быть положительной")

    bundle = torch.load(args.tensors, map_location="cpu", weights_only=False)
    if bundle.get("format") != SOURCE_FORMAT:
        raise WatercutTensorError(f"неподдерживаемый формат тензоров: {bundle.get('format')}")

    converted = dict(bundle)
    converted["format"] = OUTPUT_FORMAT
    converted["target_parameterization"] = "watercut"
    converted["target_names"] = list(WATERCUT_TARGET_NAMES)
    converted["oil_density_t_per_m3"] = args.oil_density
    converted["source_tensors"] = str(args.tensors)
    tensors = {}
    for split, triple in bundle["tensors"].items():
        x, well_index, y = triple
        watercut_targets = to_watercut_targets(y, oil_density=args.oil_density)
        tensors[split] = (x, well_index, watercut_targets)
        physical = torch.expm1(watercut_targets[:, 1].to(torch.float64))
        above = int((physical > _WATERCUT_CEILING).sum())
        print(
            f"  {split:11} узлов {len(y):>9}, обводнённость: медиана "
            f"{float(physical.median()):.4f}, выше единицы {above} "
            f"({100*above/len(physical):.3f}%)"
        )
    converted["tensors"] = tensors

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(converted, args.output)
    print(f"\nсохранено: {args.output}")
    print(
        "каналы: " + ", ".join(WATERCUT_TARGET_NAMES),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
