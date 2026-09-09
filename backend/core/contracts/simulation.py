from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .economics import NpvTable
from .response import IntervalResponse, StateAtDate

SUMMARY_EXPORT_KEYS = (
    "WLPT", "WOMT", "WWIT",  # накопленные
    "WLPR", "WOMR", "WWIR",  # мгновенные дебиты и приёмистость
    "WTHP", "WBHP",  # устьевое и забойное давление
    "WEFF",  # в экономику не входит, но колонка входного файла обязательна
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
                    f"SummarySpec.{field}: ожидалось {required!r}, получено {actual!r}"
                )


class RunStatus(Enum):
    OK = "OK"
    NOT_CONVERGED = "NOT_CONVERGED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RunResult:

    run_id: str
    status: RunStatus
    deck_hash: str  # только статическая часть дека, ключ кеша §4.5
    canonical_schedule_hash: str  # единственное имя, см. hashing.py
    summary_hash: str
    artifacts: tuple[str, ...]  # пути, вне git
    wallclock_seconds: float
    message: str


@dataclass(frozen=True, slots=True)
class OpmRunArtifact(RunResult):

    content_hash_opm: str


@dataclass(frozen=True, slots=True)
class ResponseArtifact:

    source_run_id: str  # обязан равняться OpmRunArtifact.run_id
    response_hash: str  # хеш канонической сериализации обоих типов
    state_at_date: tuple[StateAtDate, ...]
    interval_response: tuple[IntervalResponse, ...]


@dataclass(frozen=True, slots=True)
class FinalNpvArtifact:

    npv_table: NpvTable
    npv_methodology: float  # рубли, то самое число, которое заявляется
    source_run_id: str  # тот же OpmRunArtifact.run_id
    source_response_hash: str  # тот же ResponseArtifact.response_hash
    economics_config_hash: str  # хеш policies+normatives, не Config целиком
    methodology_version_hash: str  # хеш версии кода Economics

    def __post_init__(self) -> None:
        if self.npv_methodology != self.npv_table.npv_methodology:
            raise ValueError(
                "FinalNpvArtifact.npv_methodology разошлось с "
                "npv_table.npv_methodology — заявляется число не из этого "
                "разложения"
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
                    f"SubmissionBundle.{name}: обязательное поле — непустая "
                    f"строка, получено {value!r}"
                )
        if self.claimed_npv_rub != self.claimed_npv_rub:
            raise ValueError(
                "SubmissionBundle.claimed_npv_rub: NaN не допускается — "
                "заявляемое число обязано быть определено"
            )
        if self.claimed_npv_rub <= 0.0:
            raise ValueError(
                "SubmissionBundle.claimed_npv_rub: заявляемый ЧДД обязан быть "
                f"строго положительным, получено {self.claimed_npv_rub}"
            )
