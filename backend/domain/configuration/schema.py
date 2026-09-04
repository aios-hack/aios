from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields

from backend.core.contracts import (
    ArtifactHashes,
    Budgets,
    ChargeInitialEsp,
    Config,
    NormativeSet,
    Policies,
    QuantizationPolicy,
    Rule,
    canonical_bytes,
)

from backend.domain.policy.flags import DEFAULT_RULE_FLAGS
from backend.domain.policy.theta import default_theta

GLOBAL_SEED_KEY = "global"

COMPONENT_SEEDS: tuple[str, ...] = (
    "doe_planner",
    "lambda_estimator",
    "groups",
    "surrogate",
    "optimizer",
    "robustness_battery",
)

DEFAULT_BUDGETS = Budgets(
    runs_per_verification_round=8,
    fixed_point_iteration_cap=12,
)


@dataclass(frozen=True, slots=True)
class ConnectivityMeasurementParams:
    """Допуски измерения связности: два числа, которые кампания λ обязана
    получить параметром, а не прочитать литералом внутри домена.

    `injection_shortfall_tolerance` — доля недобора приёмистости, выше которой
    скважина объявляется недостижимой (`achievability_ok` = false).
    `separation_floor_share` — доля шага амплитуды; разделение фактической
    приёмистости между уровнями HIGH и LOW ниже неё означает, что столбец
    в эксперименте не участвовал.
    """

    injection_shortfall_tolerance: float
    separation_floor_share: float

    def __post_init__(self) -> None:
        if not 0.0 < self.injection_shortfall_tolerance < 1.0:
            raise ValueError(
                f"допуск недобора приёмистости — доля в (0, 1), получено "
                f"{self.injection_shortfall_tolerance}"
            )
        if not 0.0 < self.separation_floor_share < 1.0:
            raise ValueError(
                f"порог разделения — доля шага амплитуды в (0, 1), получено "
                f"{self.separation_floor_share}"
            )


DEFAULT_CONNECTIVITY_MEASUREMENT = ConnectivityMeasurementParams(
    injection_shortfall_tolerance=0.1,
    separation_floor_share=0.1,
)

_HASH_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(ArtifactHashes))


def seed_for(config: Config, component: str) -> int:
    if component != GLOBAL_SEED_KEY and component not in COMPONENT_SEEDS:
        raise ValueError(
            f"{component} не заявлен в реестре компонентов: seed берётся "
            f"только из конфига, а не назначается на месте"
        )
    if component in config.seeds:
        return config.seeds[component]
    if GLOBAL_SEED_KEY not in config.seeds:
        raise ValueError(
            f"ни {component}, ни {GLOBAL_SEED_KEY} нет в конфиге: "
            f"неконтролируемых случайных параметров быть не должно"
        )
    return config.seeds[GLOBAL_SEED_KEY]


def default_seeds(global_seed: int) -> dict[str, int]:
    seeds = {GLOBAL_SEED_KEY: global_seed}
    for offset, component in enumerate(COMPONENT_SEEDS, start=1):
        seeds[component] = global_seed + offset
    return seeds


def default_policies() -> Policies:
    return Policies(
        charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
        quantization_policy=QuantizationPolicy.NONE,
    )


def default_rules() -> dict[Rule, bool]:
    return dict(DEFAULT_RULE_FLAGS)


def default_config(
    normatives: NormativeSet,
    hashes: ArtifactHashes,
    global_seed: int,
    budgets: Budgets = DEFAULT_BUDGETS,
) -> Config:
    theta = default_theta()
    return Config(
        seeds=default_seeds(global_seed),
        policies=default_policies(),
        normatives=normatives,
        theta=dict(theta.values),
        rules=default_rules(),
        budgets=budgets,
        hashes=hashes,
    )


def validate(config: Config) -> None:
    if GLOBAL_SEED_KEY not in config.seeds:
        raise ValueError(
            f"в конфиге нет seed «{GLOBAL_SEED_KEY}»: требование сдачи — "
            f"зафиксированный seed без неконтролируемых случайных параметров"
        )
    for name, seed in config.seeds.items():
        if name != GLOBAL_SEED_KEY and name not in COMPONENT_SEEDS:
            raise ValueError(f"seed незаявленного компонента: {name}")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError(f"seed {name}={seed!r} не целый")
    missing_rules = set(Rule) - set(config.rules)
    if missing_rules:
        raise ValueError(
            f"флаги правил заданы не для всех: "
            f"{sorted(r.value for r in missing_rules)}"
        )
    for name in _HASH_FIELDS:
        value = getattr(config.hashes, name)
        if not value:
            raise ValueError(
                f"{name} пуст: хеши всех артефактов обязаны лежать в конфиге"
            )
        if len(value) != 64:
            raise ValueError(f"{name}: хеш длиной {len(value)}, ожидается 64")
    if config.budgets.runs_per_verification_round <= 0:
        raise ValueError("бюджет прогонов на раунд верификации не положителен")
    if config.budgets.fixed_point_iteration_cap <= 0:
        raise ValueError("потолок итераций неподвижной точки не положителен")


def _hashable_payload(config: Config) -> dict[str, object]:
    return {
        "seeds": dict(sorted(config.seeds.items())),
        "policies": config.policies,
        "normatives": config.normatives,
        "theta": dict(sorted(config.theta.items())),
        "rules": {rule.value: config.rules[rule] for rule in sorted(Rule, key=lambda r: r.value)},
        "budgets": config.budgets,
        "hashes": config.hashes,
    }


def config_hash(config: Config) -> str:
    validate(config)
    return hashlib.sha256(canonical_bytes(_hashable_payload(config))).hexdigest()


def economics_config_hash(config: Config) -> str:
    validate(config)
    payload = {"policies": config.policies, "normatives": config.normatives}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
