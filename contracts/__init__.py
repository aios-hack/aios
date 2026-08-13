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
    InitialEspPolicy,
    LiquidOpexPolicy,
    NormativeSet,
    Normatives,
    PartialNormativeSet,
    Policies,
    QuantizationPolicy,
    TaxPolicy,
)
from .connectivity import Groups, Lambda
from .constraints import Constraints, WellOutage
from .economics import LineItems, NpvTable
from .hashing import canonical_bytes, canonical_schedule_hash, content_hash, schedule_hash
from .policy import OptimizerResult, Rule, ScenarioViolation, Theta, TraceEntry
from .response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
    StatePair,
    join_by_control_step,
    watercut,
)
from .run_artifact import RunArtifact
from .schedule import (
    Availability,
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
    OpmRunArtifact,
    ResponseArtifact,
    RunResult,
    RunStatus,
    SubmissionArtifact,
    SummarySpec,
)

__all__ = [
    "ArtifactHashes",
    "Availability",
    "Budgets",
    "Config",
    "Constraints",
    "ControlEvent",
    "DEFAULT_NORMATIVES_2007",
    "EspCatalogEntry",
    "EventKind",
    "FinalNpvArtifact",
    "FixedDeckEvent",
    "Groups",
    "InitialEspPolicy",
    "IntervalResponse",
    "Lambda",
    "LineItems",
    "LiquidOpexPolicy",
    "N_CONTROL_DATES",
    "N_INTERVALS",
    "NormativeSet",
    "Normatives",
    "NpvTable",
    "OperatingStatus",
    "OpmRunArtifact",
    "OptimizerResult",
    "PartialNormativeSet",
    "Policies",
    "QuantizationPolicy",
    "Role",
    "RunArtifact",
    "RunResult",
    "RunStatus",
    "Rule",
    "Schedule",
    "ScheduleMeta",
    "ActiveControlMode",
    "ScenarioViolation",
    "StateAtDate",
    "StatePair",
    "SubmissionArtifact",
    "SummarySpec",
    "T0",
    "TaxPolicy",
    "Theta",
    "TraceEntry",
    "ResponseArtifact",
    "WellOutage",
    "WellState",
    "canonical_bytes",
    "canonical_schedule_hash",
    "content_hash",
    "join_by_control_step",
    "schedule_hash",
    "watercut",
]
