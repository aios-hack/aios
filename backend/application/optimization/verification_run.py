from __future__ import annotations

from backend.contexts.optimization.application.verification_run import (
    BASE_NPV,
    COMPARISON_COLUMNS,
    COMPARISON_HEADER,
    COMPARISON_SCHEMA_VERSION,
    ComparisonError,
    ComparisonInputs,
    ComparisonSide,
    ConditionCheck,
    EXPECTED_HASH,
    GuardCheck,
    GuardReport,
    GuardedVerification,
    LAMBDA,
    OIL_DENSITY_T_PER_M3,
    RESPONSE,
    VerificationGuardError,
    VerifierFn,
    WORK_ROOT,
    build_comparison_document,
    compare_baseline_to_candidate,
    equal_conditions,
    load_comparison_inputs,
    main,
    persist_observation,
    print_comparison,
    project_baseline,
    refuse_unequal_conditions,
    resolve_guard_report,
    verify_schedule,
    verify_schedule_with_guard,
)


if __name__ == "__main__":
    from backend.contexts.optimization.application.verification_run import main as _main

    raise SystemExit(_main())


__all__ = [
    "BASE_NPV",
    "COMPARISON_COLUMNS",
    "COMPARISON_HEADER",
    "COMPARISON_SCHEMA_VERSION",
    "ComparisonError",
    "ComparisonInputs",
    "ComparisonSide",
    "ConditionCheck",
    "EXPECTED_HASH",
    "GuardCheck",
    "GuardReport",
    "GuardedVerification",
    "LAMBDA",
    "OIL_DENSITY_T_PER_M3",
    "RESPONSE",
    "VerificationGuardError",
    "VerifierFn",
    "WORK_ROOT",
    "build_comparison_document",
    "compare_baseline_to_candidate",
    "equal_conditions",
    "load_comparison_inputs",
    "main",
    "persist_observation",
    "print_comparison",
    "project_baseline",
    "refuse_unequal_conditions",
    "resolve_guard_report",
    "verify_schedule",
    "verify_schedule_with_guard",
]
