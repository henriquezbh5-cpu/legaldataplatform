"""Structured logging with structlog.

JSON-formatted logs with correlation IDs enable easy aggregation in
CloudWatch, Datadog, or ELK without brittle regex parsing.
"""

import logging
import sys
from typing import Any

import structlog

from src.config import get_settings


def configure_logging() -> None:
    """Configure structlog globally. Idempotent."""
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.app.log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.dict_tracebacks,
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.app.log_level)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **context: Any) -> structlog.stdlib.BoundLogger:
    """Get a logger with optional pre-bound context."""
    logger = structlog.get_logger(name)
    if context:
        logger = logger.bind(**context)
    return logger


def bind_pipeline_context(
    pipeline_name: str,
    run_id: str,
    **extra: Any,
) -> None:
    """Bind pipeline-wide context for all subsequent logs in this thread."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        pipeline=pipeline_name,
        run_id=run_id,
        **extra,
    )
