from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.connectivity.domain.errors import CampaignError

WITHIN_WINDOW = "within-measurement"

EXTRAPOLATION = "extrapolation"

PARTIAL_EXTRAPOLATION = "partial-extrapolation"


@dataclass(frozen=True, slots=True)
class WindowApplicability:
    verdict: str
    lambda_window_start: date
    lambda_window_end: date
    horizon_start: date
    horizon_end: date
    months_before: int
    months_after: int
    covered_share: float

    @property
    def is_extrapolation(self) -> bool:
        return self.verdict != WITHIN_WINDOW

    @property
    def detail(self) -> str:
        window = f"{self.lambda_window_start}..{self.lambda_window_end}"
        horizon = f"{self.horizon_start}..{self.horizon_end}"
        if self.verdict == WITHIN_WINDOW:
            return (
                f"horizon {horizon} lies inside the lambda measurement window {window}: "
                f"the connectivity matrix is applied where it was measured"
            )
        if self.verdict == EXTRAPOLATION:
            return (
                f"horizon {horizon} lies entirely outside the lambda measurement "
                f"window {window}: all connectivity in the plan is "
                f"extrapolation, not a single month of the horizon is covered "
                f"by a measurement"
            )
        return (
            f"the lambda measurement window {window} covers "
            f"{self.covered_share:.1%} of horizon {horizon}: "
            f"{self.months_before} months before the window and "
            f"{self.months_after} months after it are extrapolation"
        )

    def as_provenance(self) -> dict[str, str]:
        return {
            "lambda_window_applicability": self.verdict,
            "lambda_window_applicability_detail": self.detail,
            "lambda_window_measured": (
                f"{self.lambda_window_start}..{self.lambda_window_end}"
            ),
            "lambda_window_horizon": f"{self.horizon_start}..{self.horizon_end}",
            "lambda_window_covered_share": f"{self.covered_share:.4f}",
            "lambda_window_months_outside": str(
                self.months_before + self.months_after
            ),
        }


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def window_applicability(
    influence: Lambda, horizon: Sequence[date]
) -> WindowApplicability:
    if not horizon:
        raise CampaignError(
            "the case horizon is empty: there is nothing to compare the lambda "
            "measurement window against, and applicability cannot be declared "
            "without a horizon"
        )
    horizon_start = min(horizon)
    horizon_end = max(horizon)
    window_start = influence.window_start
    window_end = influence.window_end
    if window_end < window_start:
        raise CampaignError(
            f"the lambda measurement window {window_start}..{window_end} is "
            f"inverted: the end precedes the start, applicability over such a "
            f"window is undefined"
        )
    months_before = max(0, _months_between(horizon_start, window_start))
    months_after = max(0, _months_between(window_end, horizon_end))
    inside = sum(1 for moment in horizon if window_start <= moment <= window_end)
    covered_share = inside / len(horizon)
    if inside == 0:
        verdict = EXTRAPOLATION
    elif inside == len(horizon):
        verdict = WITHIN_WINDOW
    else:
        verdict = PARTIAL_EXTRAPOLATION
    return WindowApplicability(
        verdict=verdict,
        lambda_window_start=window_start,
        lambda_window_end=window_end,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        months_before=months_before,
        months_after=months_after,
        covered_share=covered_share,
    )
