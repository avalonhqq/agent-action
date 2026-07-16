"""Structured JSON logging shared by HTTP and future agent workflows."""

from __future__ import annotations

import logging
from typing import cast

import structlog

from bili_support.core.config import LogLevel


def configure_logging(log_level: LogLevel) -> None:
    """Configure structlog with JSON output and request-context support."""
    level = getattr(logging, log_level.value)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return the shared structured logger facade."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())
