"""Development-tree loader for the backend package under ``src/``.

Installed builds import ``aios_backend`` from ``src`` directly.  Keeping this
small path package means the documented ``PYTHONPATH=. python -m ...`` commands
continue to work while the repository uses a conventional ``src`` layout.
"""

from pathlib import Path


__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "aios_backend")]
