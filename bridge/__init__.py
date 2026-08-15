"""Мост между контрактным расписанием и OPM Flow."""

from .cache import CachingOpmRunner, RunCache, cache_key
from .opm_deck import EmittedOpmDeck, OpmDeckEmitter, OpmDeckError, bundle_hash
from .runner import (
    DEFAULT_FLOW_ARGS,
    DEFAULT_OPM_IMAGE,
    DeckHashes,
    OpmRunner,
    OpmRunnerError,
    deck_hashes,
    static_deck_hash,
    summary_spec_hash,
)
from .summary import (
    SummaryConnection,
    SummaryPlan,
    SummaryPlanError,
    build_summary_plan,
    render_summary_include,
)

__all__ = [
    "build_summary_plan",
    "bundle_hash",
    "cache_key",
    "CachingOpmRunner",
    "deck_hashes",
    "DeckHashes",
    "DEFAULT_FLOW_ARGS",
    "DEFAULT_OPM_IMAGE",
    "EmittedOpmDeck",
    "OpmDeckEmitter",
    "OpmDeckError",
    "OpmRunner",
    "OpmRunnerError",
    "render_summary_include",
    "RunCache",
    "static_deck_hash",
    "SummaryConnection",
    "SummaryPlan",
    "SummaryPlanError",
    "summary_spec_hash",
]
