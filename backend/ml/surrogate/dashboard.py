from __future__ import annotations

from backend.interfaces.http.surrogate_dashboard.server import (
    collect_status,
    main,
)


if __name__ == "__main__":
    from backend.interfaces.http.surrogate_dashboard.server import main as _main

    raise SystemExit(_main())


__all__ = [
    "collect_status",
    "main",
]
