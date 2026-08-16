from __future__ import annotations

import pytest

from robustness import BatteryBasis, FragilityBattery, default_battery

FIRST_YEAR = 2007
LAST_YEAR = 2025
SEED = 11


@pytest.fixture
def basis() -> BatteryBasis:
    return BatteryBasis(
        injectors=tuple(f"INJ{i:02d}" for i in range(1, 28)),
        producers=tuple(f"PRD{i:02d}" for i in range(1, 63)),
        injection_level_m3_per_day=30.0,
        liquid_level_m3_per_day=110.0,
        oil_level_t_per_day=45.0,
        first_year=FIRST_YEAR,
        last_year=LAST_YEAR,
    )


@pytest.fixture
def battery(basis: BatteryBasis) -> FragilityBattery:
    return default_battery(basis, seed=SEED)
