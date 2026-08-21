from __future__ import annotations

from aios_backend.core.contracts import NormativeSet

DAYS_PER_YEAR = 365.0


def oil_margin_rub_per_t(normatives: NormativeSet) -> float:
    return (
        normatives.price_oil_rub_per_t
        - normatives.deductions_rub_per_t
        - normatives.opex_oil_rub_per_t
    )


def oil_margin_rub_per_m3_liquid(
    normatives: NormativeSet, oil_density_t_per_m3: float, watercut: float
) -> float:
    if not (0.0 <= watercut <= 1.0):
        raise ValueError(f"обводнённость {watercut} вне [0, 1]")
    return (
        (1.0 - watercut)
        * oil_density_t_per_m3
        * oil_margin_rub_per_t(normatives)
    )


def annual_margin_rub(
    normatives: NormativeSet,
    oil_density_t_per_m3: float,
    liquid_rate_m3_per_day: float,
    watercut: float,
) -> float:
    per_m3 = oil_margin_rub_per_m3_liquid(
        normatives, oil_density_t_per_m3, watercut
    ) - normatives.opex_liquid_rub_per_t
    return (
        liquid_rate_m3_per_day * DAYS_PER_YEAR * per_m3
        - normatives.opex_wellstock_rub_per_well_year
    )


def breakeven_watercut(
    normatives: NormativeSet,
    oil_density_t_per_m3: float,
    liquid_rate_m3_per_day: float,
) -> float:
    if liquid_rate_m3_per_day <= 0:
        raise ValueError("порог рентабельности не определён при нулевом дебите")
    if oil_density_t_per_m3 <= 0:
        raise ValueError("плотность нефти должна быть положительной")
    if oil_density_t_per_m3 > 10.0:
        raise ValueError(
            f"плотность {oil_density_t_per_m3} подана не в т/м³: "
            f"кг/м³ завышает маржу в тысячу раз"
        )
    margin = oil_margin_rub_per_t(normatives)
    if margin <= 0:
        raise ValueError("неположительная маржа нефти: порог не определён")
    required_per_m3 = normatives.opex_liquid_rub_per_t + (
        normatives.opex_wellstock_rub_per_well_year
        / (DAYS_PER_YEAR * liquid_rate_m3_per_day)
    )
    return 1.0 - required_per_m3 / (oil_density_t_per_m3 * margin)
