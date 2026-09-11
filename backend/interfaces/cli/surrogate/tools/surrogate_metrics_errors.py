from __future__ import annotations


class MetricsReportError(RuntimeError):
    pass


class FrozenHoldoutError(MetricsReportError):
    pass
