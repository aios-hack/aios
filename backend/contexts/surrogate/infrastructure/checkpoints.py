from __future__ import annotations

import sys
import types
from contextlib import contextmanager


@contextmanager
def _legacy_checkpoint_modules():
    """Map pre-refactor pickle names to the current package during loading.

    Production checkpoints persist :class:`TrainingDomain` as
    ``surrogate.ood.TrainingDomain``.  Importing that old package in the new
    backend can accidentally execute an unrelated editable checkout.  The
    mapping is deliberately narrow and restored immediately after
    ``torch.load``.
    """

    from backend.ml.surrogate import ood as current_ood

    names = ("surrogate", "surrogate.ood")
    previous = {name: sys.modules.get(name) for name in names}
    legacy_package = types.ModuleType("surrogate")
    legacy_package.__path__ = []  # type: ignore[attr-defined]
    legacy_package.ood = current_ood  # type: ignore[attr-defined]
    sys.modules["surrogate"] = legacy_package
    sys.modules["surrogate.ood"] = current_ood
    try:
        yield
    finally:
        for name in names:
            old = previous[name]
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
