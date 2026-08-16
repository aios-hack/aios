from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from contracts import Groups, Lambda, canonical_bytes

from connectivity.groups import (
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


class GroupsArtifactError(ValueError):
    pass


class GroupsProvenanceError(GroupsArtifactError):
    pass


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
                f"окно применимости {self.window_start}..{self.window_end} пусто "
                f"или вывернуто: артефакт без окна неотличим от артефакта "
                f"другого окна"
            )
        if not self.algorithm:
            raise GroupsProvenanceError("алгоритм не назван")
        if not self.algorithm_version:
            raise GroupsProvenanceError("версия алгоритма не названа")

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
            raise GroupsArtifactError("фонд артефакта пуст")
        for name, value in (
            ("group_hash", self.groups.group_hash),
            ("lambda_hash", self.groups.lambda_hash),
        ):
            if len(value) != HASH_LENGTH or set(value) - HEX_DIGITS:
                raise GroupsArtifactError(
                    f"{name} не является SHA-256 в {HASH_LENGTH} hex-символов: "
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
        raise GroupsArtifactError(f"в артефакте нет поля {key}")
    return payload[key]


def _parse_date(raw: Any, key: str) -> date:
    if not isinstance(raw, str):
        raise GroupsProvenanceError(f"{key}={raw!r} не строка YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise GroupsProvenanceError(f"{key}={raw!r} не разбирается как дата") from error


def _provenance_from_payload(raw: Any) -> GroupsProvenance:
    if not isinstance(raw, Mapping):
        raise GroupsProvenanceError(
            "происхождение подано не отображением: окно применимости, seed, "
            "параметры и версия алгоритма обязаны быть в артефакте"
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
            f"в происхождении нет {sorted(missing)}: артефакт без окна "
            f"применимости неотличим от артефакта другого окна"
        )
    seed = raw["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GroupsProvenanceError(f"seed={seed!r} не целый")
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
            f"нераспознанный формат артефакта: {payload.get('format')!r}"
        )
    raw_groups = _require(payload, "groups")
    if not isinstance(raw_groups, Mapping) or not raw_groups:
        raise GroupsArtifactError("нарезка подана не непустым отображением")
    groups: dict[str, tuple[str, ...]] = {}
    for group_id, members in raw_groups.items():
        if isinstance(members, str) or not isinstance(members, Sequence):
            raise GroupsArtifactError(f"участок {group_id} подан не списком скважин")
        groups[str(group_id)] = tuple(sorted(str(well) for well in members))
    raw_fund = _require(payload, "fund")
    if isinstance(raw_fund, str) or not isinstance(raw_fund, Sequence):
        raise GroupsArtifactError("фонд подан не списком скважин")
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
            f"хеш артефакта не сходится: заявлен {declared!r}, посчитан {actual!r}"
        )
    _check_invariants(artifact)
    return artifact


def _check_invariants(artifact: GroupsArtifact) -> None:
    for group_id, members in sorted(artifact.groups.groups.items()):
        if not members:
            raise GroupsArtifactError(f"участок {group_id} пуст")
    covered = {
        well for members in artifact.groups.groups.values() for well in members
    }
    missing = tuple(sorted(set(artifact.fund) - covered))
    if missing:
        raise GroupsArtifactError(
            f"вне участков осталось {len(missing)} скважин: {missing}"
        )
    stray = tuple(sorted(covered - set(artifact.fund)))
    if stray:
        raise GroupsArtifactError(
            f"в участках есть скважины вне фонда артефакта: {stray}"
        )


def loads(text: str) -> GroupsArtifact:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise GroupsArtifactError(f"артефакт не разбирается как JSON — {error}") from error
    if not isinstance(payload, Mapping):
        raise GroupsArtifactError("корень артефакта не отображение")
    return from_payload(payload)


def save(artifact: GroupsArtifact, path: Path) -> None:
    path.write_text(dumps(artifact), encoding="utf-8")


def load(path: Path) -> GroupsArtifact:
    if not path.exists():
        raise GroupsArtifactError(f"артефакт не найден: {path}")
    return loads(path.read_text(encoding="utf-8"))


def verify_against_lambda(artifact: GroupsArtifact, influence: Lambda) -> None:
    window = (influence.window_start, influence.window_end)
    if artifact.window != window:
        raise GroupsProvenanceError(
            f"окно артефакта {artifact.window[0]}..{artifact.window[1]} не совпадает "
            f"с окном матрицы {window[0]}..{window[1]}: нарезка одного окна не "
            f"применима к другому"
        )
    expected = lambda_hash(influence)
    if artifact.groups.lambda_hash != expected:
        raise GroupsProvenanceError(
            f"артефакт порождён другой матрицей: заявлен {artifact.groups.lambda_hash}, "
            f"у поданной λ {expected}"
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
            f"артефакт порождён алгоритмом {artifact.provenance.algorithm!r}, "
            f"текущий — {ALGORITHM_NAME!r}"
        )
    if artifact.provenance.algorithm_version != ALGORITHM_VERSION:
        raise GroupsProvenanceError(
            f"артефакт версии {artifact.provenance.algorithm_version}, "
            f"текущая версия алгоритма {ALGORITHM_VERSION}"
        )


def matches_params(artifact: GroupsArtifact, params: GroupingParams) -> bool:
    return artifact.provenance.params == params


def require_params(artifact: GroupsArtifact, params: GroupingParams) -> None:
    if not matches_params(artifact, params):
        stored = artifact.provenance.params
        raise GroupsProvenanceError(
            f"артефакт построен с параметрами merge_overlap={stored.merge_overlap}, "
            f"membership_share={stored.membership_share}, seed={stored.seed}; "
            f"запрошены merge_overlap={params.merge_overlap}, "
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
                f"часть ключа кеша {part!r} не является SHA-256 в "
                f"{HASH_LENGTH} hex-символов"
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
