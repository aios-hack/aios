from __future__ import annotations

from backend.interfaces.cli.surrogate.screen import (
    add_hybrid_scores,
    choose_hybrid_comparison,
    choose_model_comparison,
    choose_pair,
    known_schedule_hashes,
    main,
    transfer_fraction,
    water_margins,
)


if __name__ == "__main__":
    from backend.interfaces.cli.surrogate.screen import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "add_hybrid_scores",
    "choose_hybrid_comparison",
    "choose_model_comparison",
    "choose_pair",
    "known_schedule_hashes",
    "main",
    "transfer_fraction",
    "water_margins",
]
