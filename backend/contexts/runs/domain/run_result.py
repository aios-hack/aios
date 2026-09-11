from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.contexts.economics.domain.economics import NpvTable
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate

SUMMARY_EXPORT_KEYS = (
    "WLPT", "WOMT", "WWIT",
    "WLPR", "WOMR", "WWIR",
    "WTHP", "WBHP",
    "WEFF",
)

OPM_WELL_SUMMARY_KEYS = (
    "WLPT", "WWIT",
    "WLPR", "WWIR",
    "WTHP", "WBHP", "WEFF",
    "WMCTL",
)

OPM_CONNECTION_SUMMARY_KEYS = ("COPT", "COPR")

REQUIRED_SUMMARY_KEYS = SUMMARY_EXPORT_KEYS


MATERIAL_BALANCE_RELATIVE_TOLERANCE: float = 0.01


@dataclass(frozen=True, slots=True)
class SummarySpec:

    export_keys: tuple[str, ...] = SUMMARY_EXPORT_KEYS
    opm_well_keys: tuple[str, ...] = OPM_WELL_SUMMARY_KEYS
    opm_connection_keys: tuple[str, ...] = OPM_CONNECTION_SUMMARY_KEYS

    def __post_init__(self) -> None:
        expected = (
            ("export_keys", self.export_keys, SUMMARY_EXPORT_KEYS),
            ("opm_well_keys", self.opm_well_keys, OPM_WELL_SUMMARY_KEYS),
            (
                "opm_connection_keys",
                self.opm_connection_keys,
                OPM_CONNECTION_SUMMARY_KEYS,
            ),
        )
        for field, actual, required in expected:
            if actual != required:
                raise ValueError(
                    f"SummarySpec.{field}: expected {required!r}, got {actual!r}"
                )


class RunStatus(Enum):
    OK = "OK"
    NOT_CONVERGED = "NOT_CONVERGED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RunResult:

    run_id: str
    status: RunStatus
    deck_hash: str
    canonical_schedule_hash: str
    summary_hash: str
    artifacts: tuple[str, ...]
    wallclock_seconds: float
    message: str


@dataclass(frozen=True, slots=True)
class OpmRunArtifact(RunResult):

    content_hash_opm: str


@dataclass(frozen=True, slots=True)
class ResponseArtifact:

    source_run_id: str
    response_hash: str
    state_at_date: tuple[StateAtDate, ...]
    interval_response: tuple[IntervalResponse, ...]


@dataclass(frozen=True, slots=True)
class FinalNpvArtifact:

    npv_table: NpvTable
    npv_methodology: float
    source_run_id: str
    source_response_hash: str
    economics_config_hash: str
    methodology_version_hash: str

    def __post_init__(self) -> None:
        if self.npv_methodology != self.npv_table.npv_methodology:
            raise ValueError(
                "FinalNpvArtifact.npv_methodology disagrees with "
                "npv_table.npv_methodology — the claimed number does not come "
                "from this breakdown"
            )


@dataclass(frozen=True, slots=True)
class SubmissionArtifact:

    canonical_schedule_hash: str
    content_hash_submission: str


SUBMISSION_BUNDLE_REQUIRED_TEXT_FIELDS = (
    "canonical_schedule_hash",
    "content_hash_submission",
    "source_run_id",
    "response_hash",
    "deck_hash",
    "economics_config_hash",
    "methodology_version_hash",
    "constraints_hash",
    "opm_image",
    "git_commit",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class SubmissionBundle:
    canonical_schedule_hash: str
    content_hash_submission: str
    claimed_npv_rub: float
    source_run_id: str
    response_hash: str
    deck_hash: str
    economics_config_hash: str
    methodology_version_hash: str
    constraints_hash: str
    opm_image: str
    git_commit: str
    created_at: str

    def __post_init__(self) -> None:
        for name in SUBMISSION_BUNDLE_REQUIRED_TEXT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"SubmissionBundle.{name}: required field must be a non-empty "
                    f"string, got {value!r}"
                )
        if self.claimed_npv_rub != self.claimed_npv_rub:
            raise ValueError(
                "SubmissionBundle.claimed_npv_rub: NaN is not allowed — the claimed "
                "number must be defined"
            )
        if self.claimed_npv_rub <= 0.0:
            raise ValueError(
                "SubmissionBundle.claimed_npv_rub: the claimed NPV must be strictly "
                f"positive, got {self.claimed_npv_rub}"
            )
