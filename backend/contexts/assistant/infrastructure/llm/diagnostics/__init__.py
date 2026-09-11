from __future__ import annotations

from backend.contexts.assistant.infrastructure.llm.diagnostics.detectors import (
    detect_all,
    detect_injection_response_lag,
    detect_injection_without_response,
    detect_liquid_jump_flat_oil,
    detect_oil_rise_without_liquid,
    detect_pressure_drop_at_high_rates,
    detect_wct_rise_without_oil,
)
from backend.contexts.assistant.infrastructure.llm.diagnostics.model import (
    PATTERNS,
    Finding,
    TextClient,
    Thresholds,
)
from backend.contexts.assistant.infrastructure.llm.diagnostics.prompt import (
    build_diagnosis_prompt,
    diagnose,
)

__all__ = [
    "PATTERNS",
    "Finding",
    "TextClient",
    "Thresholds",
    "build_diagnosis_prompt",
    "detect_all",
    "detect_injection_response_lag",
    "detect_injection_without_response",
    "detect_liquid_jump_flat_oil",
    "detect_oil_rise_without_liquid",
    "detect_pressure_drop_at_high_rates",
    "detect_wct_rise_without_oil",
    "diagnose",
]
