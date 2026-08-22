from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from backend.core.contracts import (
    ArtifactHashes,
    Budgets,
    ChargeInitialEsp,
    Config,
    Policies,
    QuantizationPolicy,
    Rule,
)

from backend.domain.configuration.normatives import normatives_from_mapping
from backend.domain.configuration.schema import validate

REQUIRED_SECTIONS: tuple[str, ...] = (
    "seeds",
    "policies",
    "normatives",
    "theta",
    "rules",
    "budgets",
    "hashes",
)

_HASH_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(ArtifactHashes))
_BUDGET_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Budgets))


class ConfigError(ValueError):
    pass


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw[name]
    if not isinstance(value, Mapping):
        raise ConfigError(f"раздел {name} подан не отображением")
    return value


def _policies(raw: Mapping[str, Any]) -> Policies:
    known = {"charge_initial_esp", "quantization_policy"}
    missing = known - set(raw)
    if missing:
        raise ConfigError(f"в разделе policies нет {sorted(missing)}")
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(
            f"снятые или незаявленные политики: {sorted(unknown)}; "
            f"tax_policy и liquid_opex_policy закрыты 15.08 и не воскрешаются"
        )
    try:
        charge = ChargeInitialEsp(raw["charge_initial_esp"])
        quantization = QuantizationPolicy(raw["quantization_policy"])
    except ValueError as error:
        raise ConfigError(f"нераспознанное значение политики: {error}") from error
    return Policies(charge_initial_esp=charge, quantization_policy=quantization)


def _rules(raw: Mapping[str, Any]) -> dict[Rule, bool]:
    parsed: dict[Rule, bool] = {}
    for name, enabled in raw.items():
        try:
            rule = Rule(name)
        except ValueError as error:
            raise ConfigError(f"неизвестное правило {name}") from error
        if not isinstance(enabled, bool):
            raise ConfigError(f"флаг {name}={enabled!r} не булев")
        parsed[rule] = enabled
    missing = set(Rule) - set(parsed)
    if missing:
        raise ConfigError(
            f"флаги правил заданы не для всех: {sorted(r.value for r in missing)}"
        )
    return parsed


def _budgets(raw: Mapping[str, Any]) -> Budgets:
    missing = set(_BUDGET_FIELDS) - set(raw)
    if missing:
        raise ConfigError(f"в разделе budgets нет {sorted(missing)}")
    unknown = set(raw) - set(_BUDGET_FIELDS)
    if unknown:
        raise ConfigError(f"незаявленные бюджеты: {sorted(unknown)}")
    return Budgets(**{name: int(raw[name]) for name in _BUDGET_FIELDS})


def _hashes(raw: Mapping[str, Any]) -> ArtifactHashes:
    missing = set(_HASH_FIELDS) - set(raw)
    if missing:
        raise ConfigError(f"в разделе hashes нет {sorted(missing)}")
    unknown = set(raw) - set(_HASH_FIELDS)
    if unknown:
        raise ConfigError(f"незаявленные хеши: {sorted(unknown)}")
    return ArtifactHashes(**{name: str(raw[name]) for name in _HASH_FIELDS})


def _seeds(raw: Mapping[str, Any]) -> dict[str, int]:
    seeds: dict[str, int] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"seed {name}={value!r} не целый")
        seeds[name] = value
    return seeds


def _theta(raw: Mapping[str, Any]) -> dict[str, float]:
    return {name: float(value) for name, value in raw.items()}


def parse_config(raw: Mapping[str, Any]) -> Config:
    missing = set(REQUIRED_SECTIONS) - set(raw)
    if missing:
        raise ConfigError(f"в конфиге нет разделов {sorted(missing)}")
    unknown = set(raw) - set(REQUIRED_SECTIONS)
    if unknown:
        raise ConfigError(f"незаявленные разделы конфига: {sorted(unknown)}")
    config = Config(
        seeds=_seeds(_section(raw, "seeds")),
        policies=_policies(_section(raw, "policies")),
        normatives=normatives_from_mapping(_section(raw, "normatives")),
        theta=_theta(_section(raw, "theta")),
        rules=_rules(_section(raw, "rules")),
        budgets=_budgets(_section(raw, "budgets")),
        hashes=_hashes(_section(raw, "hashes")),
    )
    validate(config)
    return config


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"конфиг не найден: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path}: не разбирается как JSON — {error}") from error
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: корень конфига не отображение")
    return parse_config(raw)


def _as_jsonable(config: Config) -> dict[str, Any]:
    normatives: dict[str, Any] = {}
    for field in fields(config.normatives):
        value = getattr(config.normatives, field.name)
        if field.name == "esp_catalog":
            normatives[field.name] = [
                {f.name: getattr(entry, f.name) for f in fields(entry)}
                for entry in value
            ]
        else:
            normatives[field.name] = value
    return {
        "seeds": dict(config.seeds),
        "policies": {
            "charge_initial_esp": config.policies.charge_initial_esp.value,
            "quantization_policy": config.policies.quantization_policy.value,
        },
        "normatives": normatives,
        "theta": dict(config.theta),
        "rules": {rule.value: enabled for rule, enabled in config.rules.items()},
        "budgets": {
            name: getattr(config.budgets, name) for name in _BUDGET_FIELDS
        },
        "hashes": {name: getattr(config.hashes, name) for name in _HASH_FIELDS},
    }


def dump_config(config: Config, path: Path) -> None:
    validate(config)
    path.write_text(
        json.dumps(_as_jsonable(config), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
