from __future__ import annotations

from backend.contexts.connectivity.domain.errors import (
    GroupsArtifactError,
    GroupsProvenanceError,
)

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.shared.hashing import canonical_bytes

from backend.contexts.connectivity.domain.groups import (
    GroupingParams,
    GroupingReport,
    build_groups,
    group_hash,
    lambda_hash,
    validate_groups,
)

ARTIFACT_FORMAT = "aios.groups"
ALGORITHM_NAME = "lambda-overlap-union-find"
ALGORITHM_VERSION = "61.1"
HEX_DIGITS = frozenset("0123456789abcdef")
HASH_LENGTH = len(hashlib.sha256(b"").hexdigest())


@dataclass(frozen=True, slots=True)
class GroupsProvenance:
    window_start: date
    window_end: date
    algorithm: str
    algorithm_version: str
    seed: int
    merge_overlap: float
    membership_share: float

    def __post_init__(self) -> None:
        if self.window_start >= self.window_end:
            raise GroupsProvenanceError(
                f"the applicability window {self.window_start}..{self.window_end} is "
                f"empty or inverted: an artifact without a window is "
                f"indistinguishable from an artifact of another window"
            )
        if not self.algorithm:
            raise GroupsProvenanceError("the algorithm is not named")
        if not self.algorithm_version:
            raise GroupsProvenanceError("the algorithm version is not named")

    @property
    def params(self) -> GroupingParams:
        return GroupingParams(
            merge_overlap=self.merge_overlap,
            membership_share=self.membership_share,
            seed=self.seed,
        )


@dataclass(frozen=True, slots=True)
class GroupsArtifact:
    groups: Groups
    provenance: GroupsProvenance
    fund: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.fund:
            raise GroupsArtifactError("the artifact well stock is empty")
        for name, value in (
            ("group_hash", self.groups.group_hash),
            ("lambda_hash", self.groups.lambda_hash),
        ):
            if len(value) != HASH_LENGTH or set(value) - HEX_DIGITS:
                raise GroupsArtifactError(
                    f"{name} is not a SHA-256 of {HASH_LENGTH} hex characters: "
                    f"{value!r}"
                )

    @property
    def group_hash(self) -> str:
        return self.groups.group_hash

    @property
    def lambda_hash(self) -> str:
        return self.groups.lambda_hash

    @property
    def window(self) -> tuple[date, date]:
        return self.provenance.window_start, self.provenance.window_end


def provenance_of(influence: Lambda, params: GroupingParams) -> GroupsProvenance:
    return GroupsProvenance(
        window_start=influence.window_start,
        window_end=influence.window_end,
        algorithm=ALGORITHM_NAME,
        algorithm_version=ALGORITHM_VERSION,
        seed=params.seed,
        merge_overlap=params.merge_overlap,
        membership_share=params.membership_share,
    )


def build_artifact(
    influence: Lambda,
    params: GroupingParams | None = None,
    extra_wells: Sequence[str] = (),
) -> tuple[GroupsArtifact, GroupingReport]:
    settings = GroupingParams() if params is None else params
    groups, report = build_groups(influence, settings, extra_wells)
    fund = tuple(
        sorted(set(influence.producers) | set(influence.injectors) | set(extra_wells))
    )
    artifact = GroupsArtifact(
        groups=groups,
        provenance=provenance_of(influence, settings),
        fund=fund,
    )
    return artifact, report


def _normalized_groups(groups: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    return {
        str(group_id): sorted(str(well) for well in groups[group_id])
        for group_id in sorted(groups, key=str)
    }


def _normalized_provenance(provenance: GroupsProvenance) -> dict[str, Any]:
    return {
        "algorithm": provenance.algorithm,
        "algorithm_version": provenance.algorithm_version,
        "membership_share": float(provenance.membership_share),
        "merge_overlap": float(provenance.merge_overlap),
        "seed": int(provenance.seed),
        "window_end": provenance.window_end.isoformat(),
        "window_start": provenance.window_start.isoformat(),
    }


def normalized_payload(artifact: GroupsArtifact) -> dict[str, Any]:
    return {
        "format": ARTIFACT_FORMAT,
        "fund": sorted(str(well) for well in artifact.fund),
        "groups": _normalized_groups(artifact.groups.groups),
        "lambda_hash": artifact.groups.lambda_hash,
        "provenance": _normalized_provenance(artifact.provenance),
    }


def artifact_hash(artifact: GroupsArtifact) -> str:
    return hashlib.sha256(canonical_bytes(normalized_payload(artifact))).hexdigest()


def to_payload(artifact: GroupsArtifact) -> dict[str, Any]:
    payload = normalized_payload(artifact)
    payload["group_hash"] = artifact.groups.group_hash
    payload["artifact_hash"] = artifact_hash(artifact)
    return payload


def dumps(artifact: GroupsArtifact) -> str:
    return json.dumps(
        to_payload(artifact), ensure_ascii=False, sort_keys=True, indent=2
    )


def _require(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload:
        raise GroupsArtifactError(f"the artifact has no field {key}")
    return payload[key]


def _parse_date(raw: Any, key: str) -> date:
    if not isinstance(raw, str):
        raise GroupsProvenanceError(f"{key}={raw!r} is not a YYYY-MM-DD string")
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise GroupsProvenanceError(f"{key}={raw!r} does not parse as a date") from error


def _provenance_from_payload(raw: Any) -> GroupsProvenance:
    if not isinstance(raw, Mapping):
        raise GroupsProvenanceError(
            "provenance is not given as a mapping: the applicability window, seed, "
            "parameters and algorithm version must all be in the artifact"
        )
    missing = {
        "algorithm",
        "algorithm_version",
        "membership_share",
        "merge_overlap",
        "seed",
        "window_end",
        "window_start",
    } - set(raw)
    if missing:
        raise GroupsProvenanceError(
            f"provenance is missing {sorted(missing)}: an artifact without an "
            f"applicability window is indistinguishable from an artifact of "
            f"another window"
        )
    seed = raw["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GroupsProvenanceError(f"seed={seed!r} is not an integer")
    return GroupsProvenance(
        window_start=_parse_date(raw["window_start"], "window_start"),
        window_end=_parse_date(raw["window_end"], "window_end"),
        algorithm=str(raw["algorithm"]),
        algorithm_version=str(raw["algorithm_version"]),
        seed=seed,
        merge_overlap=float(raw["merge_overlap"]),
        membership_share=float(raw["membership_share"]),
    )


def from_payload(payload: Mapping[str, Any]) -> GroupsArtifact:
    if payload.get("format") != ARTIFACT_FORMAT:
        raise GroupsArtifactError(
            f"unrecognised artifact format: {payload.get('format')!r}"
        )
    raw_groups = _require(payload, "groups")
    if not isinstance(raw_groups, Mapping) or not raw_groups:
        raise GroupsArtifactError("the grouping is not given as a non-empty mapping")
    groups: dict[str, tuple[str, ...]] = {}
    for group_id, members in raw_groups.items():
        if isinstance(members, str) or not isinstance(members, Sequence):
            raise GroupsArtifactError(f"group {group_id} is not given as a list of wells")
        groups[str(group_id)] = tuple(sorted(str(well) for well in members))
    raw_fund = _require(payload, "fund")
    if isinstance(raw_fund, str) or not isinstance(raw_fund, Sequence):
        raise GroupsArtifactError("the well stock is not given as a list of wells")
    artifact = GroupsArtifact(
        groups=Groups(
            groups=groups,
            lambda_hash=str(_require(payload, "lambda_hash")),
            group_hash=str(_require(payload, "group_hash")),
        ),
        provenance=_provenance_from_payload(_require(payload, "provenance")),
        fund=tuple(sorted(str(well) for well in raw_fund)),
    )
    declared = payload.get("artifact_hash")
    actual = artifact_hash(artifact)
    if declared is not None and declared != actual:
        raise GroupsArtifactError(
            f"the artifact hash does not match: declared {declared!r}, computed {actual!r}"
        )
    _check_invariants(artifact)
    return artifact


def _check_invariants(artifact: GroupsArtifact) -> None:
    for group_id, members in sorted(artifact.groups.groups.items()):
        if not members:
            raise GroupsArtifactError(f"group {group_id} is empty")
    covered = {
        well for members in artifact.groups.groups.values() for well in members
    }
    missing = tuple(sorted(set(artifact.fund) - covered))
    if missing:
        raise GroupsArtifactError(
            f"{len(missing)} wells are left outside the groups: {missing}"
        )
    stray = tuple(sorted(covered - set(artifact.fund)))
    if stray:
        raise GroupsArtifactError(
            f"the groups contain wells outside the artifact well stock: {stray}"
        )


def loads(text: str) -> GroupsArtifact:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise GroupsArtifactError(f"the artifact does not parse as JSON — {error}") from error
    if not isinstance(payload, Mapping):
        raise GroupsArtifactError("the artifact root is not a mapping")
    return from_payload(payload)


def save(artifact: GroupsArtifact, path: Path) -> None:
    path.write_text(dumps(artifact), encoding="utf-8")


def load(path: Path) -> GroupsArtifact:
    if not path.exists():
        raise GroupsArtifactError(f"artifact not found: {path}")
    return loads(path.read_text(encoding="utf-8"))


def verify_against_lambda(artifact: GroupsArtifact, influence: Lambda) -> None:
    window = (influence.window_start, influence.window_end)
    if artifact.window != window:
        raise GroupsProvenanceError(
            f"the artifact window {artifact.window[0]}..{artifact.window[1]} does "
            f"not match the matrix window {window[0]}..{window[1]}: a grouping "
            f"of one window does not apply to another"
        )
    expected = lambda_hash(influence)
    if artifact.groups.lambda_hash != expected:
        raise GroupsProvenanceError(
            f"the artifact came from a different matrix: it declares "
            f"{artifact.groups.lambda_hash}, the given lambda has {expected}"
        )
    validate_groups(artifact.groups, influence, artifact.fund)


def is_current(artifact: GroupsArtifact) -> bool:
    return (
        artifact.provenance.algorithm == ALGORITHM_NAME
        and artifact.provenance.algorithm_version == ALGORITHM_VERSION
    )


def require_current(artifact: GroupsArtifact) -> None:
    if artifact.provenance.algorithm != ALGORITHM_NAME:
        raise GroupsProvenanceError(
            f"the artifact came from algorithm {artifact.provenance.algorithm!r}, "
            f"the current one is {ALGORITHM_NAME!r}"
        )
    if artifact.provenance.algorithm_version != ALGORITHM_VERSION:
        raise GroupsProvenanceError(
            f"the artifact is of version {artifact.provenance.algorithm_version}, "
            f"the current algorithm version is {ALGORITHM_VERSION}"
        )


def matches_params(artifact: GroupsArtifact, params: GroupingParams) -> bool:
    return artifact.provenance.params == params


def require_params(artifact: GroupsArtifact, params: GroupingParams) -> None:
    if not matches_params(artifact, params):
        stored = artifact.provenance.params
        raise GroupsProvenanceError(
            f"the artifact was built with merge_overlap={stored.merge_overlap}, "
            f"membership_share={stored.membership_share}, seed={stored.seed}; "
            f"requested merge_overlap={params.merge_overlap}, "
            f"membership_share={params.membership_share}, seed={params.seed}"
        )


def reusable_for(
    artifact: GroupsArtifact, influence: Lambda, params: GroupingParams
) -> bool:
    try:
        require_current(artifact)
        require_params(artifact, params)
        verify_against_lambda(artifact, influence)
    except GroupsArtifactError:
        return False
    return True


def cache_key(artifact: GroupsArtifact, *parts: str) -> str:
    digests = [bytes.fromhex(artifact_hash(artifact))]
    for part in parts:
        if len(part) != HASH_LENGTH or set(part) - HEX_DIGITS:
            raise GroupsArtifactError(
                f"cache key part {part!r} is not a SHA-256 of "
                f"{HASH_LENGTH} hex characters"
            )
        digests.append(bytes.fromhex(part))
    return hashlib.sha256(b"".join(digests)).hexdigest()


def rehash(artifact: GroupsArtifact, influence: Lambda) -> GroupsArtifact:
    params = artifact.provenance.params
    return replace(
        artifact,
        groups=Groups(
            groups=dict(artifact.groups.groups),
            lambda_hash=lambda_hash(influence),
            group_hash=group_hash(artifact.groups.groups, influence, params),
        ),
    )
