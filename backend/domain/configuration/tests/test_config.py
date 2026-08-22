from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

from backend.core.contracts import (
    ArtifactHashes,
    ChargeInitialEsp,
    Config,
    NormativeSet,
    QuantizationPolicy,
    Rule,
)

from backend.domain.configuration import (
    COMPONENT_SEEDS,
    GLOBAL_SEED_KEY,
    ConfigError,
    config_hash,
    dump_config,
    economics_config_hash,
    load_config,
    parse_config,
    seed_for,
)
from backend.domain.configuration.io import _as_jsonable
from backend.domain.configuration.schema import validate

from backend.domain.configuration.tests.conftest import GLOBAL_SEED, a_hash


def test_every_section_of_the_contract_is_present(config: Config) -> None:
    raw = _as_jsonable(config)
    assert set(raw) == {
        "seeds",
        "policies",
        "normatives",
        "theta",
        "rules",
        "budgets",
        "hashes",
    }


def test_seed_is_fixed_and_reachable_for_every_component(config: Config) -> None:
    assert config.seeds[GLOBAL_SEED_KEY] == GLOBAL_SEED
    for component in COMPONENT_SEEDS:
        assert isinstance(seed_for(config, component), int)


def test_component_without_own_seed_falls_back_to_global(config: Config) -> None:
    trimmed = replace(config, seeds={GLOBAL_SEED_KEY: GLOBAL_SEED})
    assert seed_for(trimmed, "optimizer") == GLOBAL_SEED


def test_unregistered_component_cannot_invent_a_seed(config: Config) -> None:
    with pytest.raises(ValueError, match="не заявлен в реестре компонентов"):
        seed_for(config, "my_new_thing")


def test_config_without_global_seed_is_rejected(config: Config) -> None:
    with pytest.raises(ValueError, match="зафиксированный seed"):
        validate(replace(config, seeds={"optimizer": 1}))


def test_all_artifact_hashes_live_in_the_config(config: Config) -> None:
    for field in fields(ArtifactHashes):
        value = getattr(config.hashes, field.name)
        assert len(value) == 64


def test_empty_artifact_hash_is_rejected(config: Config) -> None:
    broken = replace(config.hashes, groups_hash="")
    with pytest.raises(ValueError, match="хеши всех артефактов"):
        validate(replace(config, hashes=broken))


def test_short_artifact_hash_is_rejected(config: Config) -> None:
    broken = replace(config.hashes, deck_hash="abc")
    with pytest.raises(ValueError, match="ожидается 64"):
        validate(replace(config, hashes=broken))


def test_two_policies_remain_and_defaults_mirror_the_reference(
    config: Config,
) -> None:
    assert set(f.name for f in fields(config.policies)) == {
        "charge_initial_esp",
        "quantization_policy",
    }
    assert config.policies.charge_initial_esp is ChargeInitialEsp.NOT_CHARGED
    assert config.policies.quantization_policy is QuantizationPolicy.NONE


def test_removed_policies_are_not_accepted(config: Config) -> None:
    raw = _as_jsonable(config)
    raw["policies"]["tax_policy"] = "ALWAYS"
    with pytest.raises(ConfigError, match="tax_policy и liquid_opex_policy закрыты"):
        parse_config(raw)


def test_flags_are_declared_for_every_rule(config: Config) -> None:
    assert set(config.rules) == set(Rule)


def test_missing_rule_flag_is_rejected(config: Config) -> None:
    partial = {rule: True for rule in Rule if rule is not Rule.R7}
    with pytest.raises(ValueError, match="заданы не для всех"):
        validate(replace(config, rules=partial))


def test_normatives_are_one_scalar_set_without_a_year_axis(
    config: Config,
) -> None:
    raw = _as_jsonable(config)["normatives"]
    assert "by_year" not in raw
    assert "base" not in raw
    assert raw["income_tax_rate"] == 0.25
    assert raw["conversion_base_cost_rub"] == 5_000_000.0


def test_rates_given_as_percent_are_rejected(config: Config) -> None:
    raw = _as_jsonable(config)
    raw["normatives"]["income_tax_rate"] = 25.0
    with pytest.raises(ValueError, match="подан процентами"):
        parse_config(raw)


def test_partial_normatives_are_rejected(config: Config) -> None:
    raw = _as_jsonable(config)
    del raw["normatives"]["price_oil_rub_per_t"]
    with pytest.raises(ValueError, match="умолчаний у нормативов нет"):
        parse_config(raw)


def test_round_trip_through_file_preserves_the_config(
    config: Config, tmp_path: Path
) -> None:
    path = tmp_path / "run.json"
    dump_config(config, path)
    restored = load_config(path)
    assert restored == config
    assert config_hash(restored) == config_hash(config)


def test_config_hash_is_stable_and_sensitive(config: Config) -> None:
    assert config_hash(config) == config_hash(config)
    moved = replace(config, seeds={**config.seeds, GLOBAL_SEED_KEY: GLOBAL_SEED + 1})
    assert config_hash(moved) != config_hash(config)


def test_economics_hash_covers_only_policies_and_normatives(
    config: Config,
) -> None:
    baseline = economics_config_hash(config)
    retuned = replace(config, theta={**config.theta, "r1_lag_months": 5.0})
    assert economics_config_hash(retuned) == baseline
    assert config_hash(retuned) != config_hash(config)

    repriced = replace(
        config,
        normatives=replace(config.normatives, price_oil_rub_per_t=30_000.0),
    )
    assert economics_config_hash(repriced) != baseline


def test_rule_flag_change_does_not_invalidate_the_economics_hash(
    config: Config,
) -> None:
    baseline = economics_config_hash(config)
    flipped = replace(config, rules={**config.rules, Rule.R2: False})
    assert economics_config_hash(flipped) == baseline


def test_unknown_section_is_rejected(config: Config) -> None:
    raw = _as_jsonable(config)
    raw["extra"] = {}
    with pytest.raises(ConfigError, match="незаявленные разделы"):
        parse_config(raw)


def test_missing_section_is_rejected(config: Config) -> None:
    raw = _as_jsonable(config)
    del raw["budgets"]
    with pytest.raises(ConfigError, match="нет разделов"):
        parse_config(raw)


def test_non_integer_seed_is_rejected(config: Config) -> None:
    raw = _as_jsonable(config)
    raw["seeds"][GLOBAL_SEED_KEY] = 1.5
    with pytest.raises(ConfigError, match="не целый"):
        parse_config(raw)


def test_budgets_must_be_positive(config: Config) -> None:
    with pytest.raises(ValueError, match="не положителен"):
        validate(replace(config, budgets=replace(config.budgets, fixed_point_iteration_cap=0)))


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="конфиг не найден"):
        load_config(tmp_path / "absent.json")


def test_broken_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="не разбирается как JSON"):
        load_config(path)
