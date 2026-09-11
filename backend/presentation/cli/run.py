from __future__ import annotations

from backend.interfaces.cli.run import (
    build_parser,
    build_provenance,
    compare,
    default_case_path,
    load_run_request,
    load_saved_constraints,
    load_saved_provenance,
    main,
    require_docker,
    resolve_case,
    resolve_comparison_case,
    resolve_constraints,
    resolve_model_dir,
    resolve_normatives_sha256,
    submit,
)


if __name__ == "__main__":
    from backend.interfaces.cli.run import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "build_parser",
    "build_provenance",
    "compare",
    "default_case_path",
    "load_run_request",
    "load_saved_constraints",
    "load_saved_provenance",
    "main",
    "require_docker",
    "resolve_case",
    "resolve_comparison_case",
    "resolve_constraints",
    "resolve_model_dir",
    "resolve_normatives_sha256",
    "submit",
]
