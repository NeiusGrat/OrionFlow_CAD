"""
Structured Logging Configuration for OrionFlow_CAD.

Provides consistent, JSON-formatted logging across the application using structlog.
Includes request ID tracking for distributed tracing.

Usage:
    from app.logging_config import get_logger
    
    logger = get_logger(__name__)
    logger.info("generation_started", job_id=job_id, prompt=prompt[:50])
"""
import sys
import logging
import uuid
from contextvars import ContextVar
from typing import Optional

import structlog
from structlog.types import Processor

from app.config import settings

# Context variable for request tracking
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_id_ctx.get()


def set_request_id(request_id: str) -> None:
    """Set request ID in context."""
    request_id_ctx.set(request_id)


def generate_request_id() -> str:
    """Generate a new request ID."""
    return str(uuid.uuid4())[:8]


def add_request_id(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict
) -> dict:
    """Structlog processor to add request ID to log entries."""
    request_id = get_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def add_service_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict
) -> dict:
    """Add service-level context to all log entries."""
    event_dict["service"] = "orionflow-cad"
    event_dict["version"] = "0.2.0"
    return event_dict


def configure_logging() -> None:
    """
    Configure structured logging for the application.
    
    Call this once at application startup.
    """
    # Determine if we're in debug mode
    debug = settings.debug
    log_level = settings.log_level
    
    # Shared processors for all output
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_request_id,
        add_service_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if debug:
        # Development: Pretty console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    else:
        # Production: JSON output for log aggregation
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ]
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )
    
    # Set log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("groq").setLevel(logging.WARNING)


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


# Pre-configured loggers for common modules
class Loggers:
    """Pre-configured logger instances for common modules."""
    
    @staticmethod
    def api() -> structlog.stdlib.BoundLogger:
        """Logger for API layer."""
        return get_logger("app.api")
    
    @staticmethod
    def generation() -> structlog.stdlib.BoundLogger:
        """Logger for generation service."""
        return get_logger("app.services.generation")
    
    @staticmethod
    def llm() -> structlog.stdlib.BoundLogger:
        """Logger for LLM client."""
        return get_logger("app.llm")
    
    @staticmethod
    def compiler() -> structlog.stdlib.BoundLogger:
        """Logger for compilers."""
        return get_logger("app.compilers")
    
    @staticmethod
    def dataset() -> structlog.stdlib.BoundLogger:
        """Logger for dataset operations."""
        return get_logger("app.dataset")
