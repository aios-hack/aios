"""Общие типы проекта. Единственная общая поверхность между пакетами.

Полная спецификация с обоснованиями — README.md рядом с этим файлом и
docs/context/08_contracts.md. Здесь — просто импорт того, что там описано,
в исполняемом виде: не переизобретайте эти типы в своём пакете, импортируйте
отсюда.

Правит только интегратор (README.md, "Правило"). Нужна правка — issue, не
самовольный коммит в этот каталог.
"""

from .config import (
    ArtifactHashes,
    Budgets,
    Config,
    DEFAULT_NORMATIVES_2007,
    EspCatalogEntry,
    ChargeInitialEsp,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from .connectivity import Groups, Lambda
from .constraints import Constraints, WellOutage
from .economics import LineItems, NpvTable
from .hashing import canonical_bytes, canonical_schedule_hash, content_hash, hash_schedule
from .policy import OptimizerResult, Rule, ScenarioViolation, Theta, TraceEntry
from .response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
    StatePair,
    is_excluded_by_negative_rule,
    join_by_control_step,
    watercut,
)
from .run_artifact import RunArtifact
from .schedule import (
    Availability,
    MAX_LRAT_M3_PER_DAY,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_CONTROL_DATES,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    T0,
    WellState,
)
from .simulation import (
    FinalNpvArtifact,
    OPM_CONNECTION_SUMMARY_KEYS,
    OPM_WELL_SUMMARY_KEYS,
    OpmRunArtifact,
    ResponseArtifact,
    RunResult,
    RunStatus,
    SUMMARY_EXPORT_KEYS,
    SubmissionArtifact,
    SummarySpec,
)

__all__ = [
    "ActiveControlMode",
    "ArtifactHashes",
    "Availability",
    "Budgets",
    "canonical_bytes",
    "canonical_schedule_hash",
    "ChargeInitialEsp",
    "Config",
    "Constraints",
    "content_hash",
    "ControlEvent",
    "DEFAULT_NORMATIVES_2007",
    "EspCatalogEntry",
    "EventKind",
    "FinalNpvArtifact",
    "FixedDeckEvent",
    "Groups",
    "hash_schedule",
    "IntervalResponse",
    "is_excluded_by_negative_rule",
    "join_by_control_step",
    "Lambda",
    "LineItems",
    "MAX_LRAT_M3_PER_DAY",
    "N_CONTROL_DATES",
    "N_INTERVALS",
    "NormativeSet",
    "NpvTable",
    "OperatingStatus",
    "OPM_CONNECTION_SUMMARY_KEYS",
    "OPM_WELL_SUMMARY_KEYS",
    "OpmRunArtifact",
    "OptimizerResult",
    "Policies",
    "QuantizationPolicy",
    "ResponseArtifact",
    "Role",
    "Rule",
    "RunArtifact",
    "RunResult",
    "RunStatus",
    "ScenarioViolation",
    "Schedule",
    "ScheduleMeta",
    "SUMMARY_EXPORT_KEYS",
    "StateAtDate",
    "StatePair",
    "SubmissionArtifact",
    "SummarySpec",
    "T0",
    "Theta",
    "TraceEntry",
    "watercut",
    "WellOutage",
    "WellState",
]
