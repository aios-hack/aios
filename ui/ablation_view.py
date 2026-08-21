"""Разложение ЧДД по правилам политики для вида «Итог» (F15).

`delta_npv: null` — правило не измерялось; `delta_npv: 0.0` — измеренный
ноль, правило работало и вклада не дало. Это разные утверждения, и
интерфейс обязан их различать, поэтому демо-набор содержит оба случая и
выключенное правило с причиной: рендер обоих веток не должен зависеть от
того, повезло ли генератору.

Источник настоящих величин — `policy/trace.py::ablation_delta` на паре
прогонов «с правилом / без правила»; такой пары нет, поэтому здесь
правдоподобные доли от ЧДД артефакта с фиксированным seed. Формулировки
правил в данные не кладутся — они в i18n интерфейса.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts import Rule, RunArtifact

from ui.demo_rng import Rng
from ui.timeline import _JSON_DIGITS

UPLIFT_NOT_MEASURED = "UPLIFT_NOT_MEASURED"

MEASURED_RULES: tuple[str, ...] = ("R0", "R1", "R3", "R4")
ZERO_RULES: tuple[str, ...] = ("R5",)
UNMEASURED_RULES: tuple[str, ...] = ("R2", "R6")
DISABLED_RULES: dict[str, str] = {"R7": UPLIFT_NOT_MEASURED}

_SHARE_LOW: float = 0.02
_SHARE_HIGH: float = 0.13


def _round(value: float) -> float:
    rounded = round(value, _JSON_DIGITS)
    return int(rounded) if float(rounded).is_integer() else rounded


def build_ablation(artifact: RunArtifact, seed: int) -> dict[str, Any]:
    npv_total = artifact.npv_table.npv_methodology
    rng = Rng(seed)
    rules: list[dict[str, Any]] = []
    for rule in sorted(Rule, key=lambda item: item.value):
        name = rule.value
        if name in DISABLED_RULES:
            rules.append(
                {
                    "rule": name,
                    "enabled": False,
                    "delta_npv": None,
                    "share": None,
                    "disabled_reason": DISABLED_RULES[name],
                }
            )
            continue
        if name in UNMEASURED_RULES:
            rules.append(
                {"rule": name, "enabled": True, "delta_npv": None, "share": None}
            )
            continue
        if name in ZERO_RULES:
            rules.append(
                {"rule": name, "enabled": True, "delta_npv": 0.0, "share": 0.0}
            )
            continue
        if name not in MEASURED_RULES:
            raise ValueError(
                f"{name} не отнесено ни к измеренным, ни к неизмеренным, ни к "
                f"выключенным: молчаливо пропустить правило нельзя"
            )
        share = _round(rng.between(_SHARE_LOW, _SHARE_HIGH))
        rules.append(
            {
                "rule": name,
                "enabled": True,
                "delta_npv": _round(npv_total * share),
                "share": share,
            }
        )
    return {"npv_total": _round(npv_total), "rules": rules}


def export_ablation_json(
    artifact: RunArtifact, out_path: str | Path, seed: int
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_ablation(artifact, seed),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out
