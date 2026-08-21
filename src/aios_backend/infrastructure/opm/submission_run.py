"""Compatibility entry point for the moved verification scenario.

The OPM package supplies adapters.  The executable scenario belongs to the
application layer; this file preserves ``python -m bridge.submission_run``.
"""

from aios_backend.application.optimization.verification_run import *
from aios_backend.application.optimization.verification_run import main


if __name__ == "__main__":
    raise SystemExit(main())
