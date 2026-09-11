from __future__ import annotations

import logging
import sys
from typing import TextIO

ROOT_LOGGER = "backend"
DEFAULT_LEVEL = logging.INFO
LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"
_CONFIGURED = False


def configure(level: int = DEFAULT_LEVEL, stream: TextIO | None = None) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger(ROOT_LOGGER)
    if _CONFIGURED:
        return logger
    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    _CONFIGURED = True
    return logger


def reset() -> None:
    global _CONFIGURED
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    _CONFIGURED = False


__all__ = ["DEFAULT_LEVEL", "LOG_FORMAT", "ROOT_LOGGER", "configure", "reset"]
