"""Published and reproducible Model Z baseline anchors.

The organizer's published tNavigator CSV reports the whole project on a
1991 discount basis.  Our optimization objective contains only the
controllable 2007--2025 horizon and uses 2007 as its discount basis.  Those
numbers must be rebased before they are compared.
"""

from __future__ import annotations


# ``Расчет ЧДД через тНавигатор Model_Z.csv``, published 30.08.2026.
TNAV_FULL_PROJECT_BASE_NPV_RUB = 5_218_944_908.0841405
TNAV_HISTORY_THROUGH_2006_NPV_RUB = 2_628_291_293.9187512
TNAV_CONTROL_START_DISCOUNT_FACTOR = 0.2176291357901485

# The same published tNavigator cash flow, restricted to 2007--2025 and
# rebased to 2007.  This is the comparable value for our optimizer.
TNAV_CONTROL_HORIZON_BASE_NPV_RUB = (
    TNAV_FULL_PROJECT_BASE_NPV_RUB - TNAV_HISTORY_THROUGH_2006_NPV_RUB
) / TNAV_CONTROL_START_DISCOUNT_FACTOR

# Reproducible OPM response ``data/base_case/response.json`` evaluated by the
# organizer's reference calculator on the same 2007--2025 objective basis.
OPM_CONTROL_HORIZON_BASE_NPV_RUB = 11_873_122_324.910866


def rebase_control_horizon_to_published_full_project(
    control_horizon_npv_rub: float,
) -> float:
    """Map a 2007-based value onto the published tNavigator 1991 basis.

    This keeps the published tNavigator history fixed.  For OPM it is a
    comparison aid, not a replacement for the organizer's OPM CSV, because
    the two simulators may also differ on the historical prefix.
    """

    return (
        TNAV_HISTORY_THROUGH_2006_NPV_RUB
        + TNAV_CONTROL_START_DISCOUNT_FACTOR * control_horizon_npv_rub
    )
