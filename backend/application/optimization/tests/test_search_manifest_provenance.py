from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.contexts.runs.application.workflow import (
    MANIFEST_PROVENANCE_FIELDS,
    RunManifest,
    RunProvenance,
    WorkflowStatus,
)
from backend.core.contracts import Constraints
from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash

from .test_search_scoring_and_provenance import (
    _run_search_module,
    _run_search_stubs,
)

UNAVAILABLE_AFTER_SEARCH: frozenset[str] = frozenset({"deck_hash"})

SUPPLIED_BY_THE_CLI: frozenset[str] = frozenset(
    {"normatives_sha256", "opm_image", "git_commit"}
)

DERIVED_FROM_THE_OUTCOME: frozenset[str] = frozenset(
    {"iterations", "self_consistent"}
)


def build_provenance_like_the_cli(
    outcome: Any, constraints: Constraints | None
) -> RunProvenance:
    recorded: dict[str, str] = dict(outcome.provenance)
    evaluations = outcome.evaluations
    self_consistent = outcome.self_consistent
    return RunProvenance(
        model_version=recorded.get("model_version"),
        npv_head_version=recorded.get("npv_head_version"),
        scenario_ood_version=recorded.get("scenario_ood_version"),
        feature_context_sha256=recorded.get("feature_context_sha256"),
        constraints_hash=(
            constraints_hash(constraints) if constraints is not None else None
        ),
        deck_hash=None,
        normatives_sha256="n" * 64,
        opm_image="opm:test",
        git_commit="c" * 40,
        seed=recorded.get("seed"),
        search_strategy=recorded.get("search_strategy"),
        policy_equilibrium=recorded.get("policy_equilibrium"),
        iterations=evaluations if isinstance(evaluations, int) else None,
        self_consistent=(
            self_consistent if isinstance(self_consistent, bool) else None
        ),
    )


@pytest.fixture
def search_outcome(tmp_path: Path) -> Any:
    diagnostics = tmp_path / "cmaes-diagnostics.json"
    diagnostics.write_text('{"evaluations": []}', encoding="utf-8")
    context = tmp_path / "feature_context.json"
    context.write_bytes(b"feature-context")
    overrides = dict(
        _run_search_stubs("converged", {}, feature_context=context)
    )
    overrides["SEARCH_DIAGNOSTICS"] = diagnostics
    overrides["print"] = lambda *args, **kwargs: None
    namespace = _run_search_module(overrides)
    return namespace["run_search"]()


def test_search_records_the_feature_context_digest(
    search_outcome: Any, tmp_path: Path
) -> None:
    expected = hashlib.sha256(b"feature-context").hexdigest()

    assert search_outcome.provenance["feature_context_sha256"] == expected


def test_search_records_the_constraints_hash(search_outcome: Any) -> None:
    assert search_outcome.provenance["constraints_hash"] == constraints_hash(
        Constraints()
    )


def test_manifest_after_search_has_no_null_in_available_fields(
    search_outcome: Any,
) -> None:
    provenance = build_provenance_like_the_cli(search_outcome, Constraints())
    manifest = RunManifest(
        run_id="run-test",
        status=WorkflowStatus.SEARCHED,
        schedule_hash="h" * 64,
        predicted_npv=1.0,
        verified_npv=None,
        sound=None,
        **{name: getattr(provenance, name) for name in MANIFEST_PROVENANCE_FIELDS},
    )
    document = manifest.as_dict()

    empty = [
        name
        for name in MANIFEST_PROVENANCE_FIELDS
        if document[name] is None and name not in UNAVAILABLE_AFTER_SEARCH
    ]

    assert not empty, (
        "после поиска манифест оставил пустыми поля провенанса, значение "
        f"которых известно: {sorted(empty)}"
    )


def test_the_only_unavailable_field_is_the_deck_hash(search_outcome: Any) -> None:
    provenance = build_provenance_like_the_cli(search_outcome, Constraints())
    document = RunManifest(
        run_id="run-test",
        status=WorkflowStatus.SEARCHED,
        schedule_hash="h" * 64,
        predicted_npv=1.0,
        verified_npv=None,
        sound=None,
        **{name: getattr(provenance, name) for name in MANIFEST_PROVENANCE_FIELDS},
    ).as_dict()

    assert [
        name for name in MANIFEST_PROVENANCE_FIELDS if document[name] is None
    ] == ["deck_hash"]


def test_every_manifest_field_has_a_named_supplier(search_outcome: Any) -> None:
    recorded = set(search_outcome.provenance)
    unexplained = [
        name
        for name in MANIFEST_PROVENANCE_FIELDS
        if name not in recorded
        and name not in UNAVAILABLE_AFTER_SEARCH
        and name not in SUPPLIED_BY_THE_CLI
        and name not in DERIVED_FROM_THE_OUTCOME
    ]

    assert not unexplained, (
        "поля манифеста без источника: их никто не заполняет, и в манифесте "
        f"они окажутся null — {sorted(unexplained)}"
    )


def test_an_unreadable_feature_context_is_an_error_not_a_blank(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "cmaes-diagnostics.json"
    diagnostics.write_text('{"evaluations": []}', encoding="utf-8")
    overrides = dict(
        _run_search_stubs(
            "converged", {}, feature_context=tmp_path / "absent.json"
        )
    )
    overrides["SEARCH_DIAGNOSTICS"] = diagnostics
    overrides["print"] = lambda *args, **kwargs: None
    namespace = _run_search_module(overrides)

    with pytest.raises(namespace["SearchRunError"], match="feature_context"):
        namespace["run_search"]()
