"""Structured logging configuration for ChatBotura - JSON format with context."""
import os
import sys
import json
import hashlib
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Optional
from logging import StreamHandler, Formatter


# ============================================================================
# Log Level Configuration
# ============================================================================

# Map environment to log levels
LOG_LEVEL_ENV = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
LOG_LEVEL = LOG_LEVELS.get(LOG_LEVEL_ENV, logging.INFO)


# ============================================================================
# JSON Formatter
# ============================================================================

class StructuredLogFormatter(Formatter):
    """
    JSON formatter for structured logging.
    
    Includes: timestamp, level, message, tenant_id, session_id, user_message_hash, latency_ms
    """
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        # Build base log entry
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present (set via logging context)
        if self.include_extra:
            extra_fields = [
                "tenant_id", "session_id", "user_message_hash", 
                "latency_ms", "request_id", "span_id"
            ]
            for field in extra_fields:
                value = getattr(record, field, None)
                if value is not None:
                    log_entry[field] = value
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Add any custom attributes from extra
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)
        
        return json.dumps(log_entry, default=str)


# ============================================================================
# Logging Context (for setting context per request)
# ============================================================================

class LogContext:
    """
    Context manager for setting logging context.
    
    Usage:
        with LogContext(tenant_id="pizza_shop", session_id="abc123"):
            logger.info("Processing request")  # {"tenant_id": "pizza_shop", "session_id": "abc123", ...}
    """
    
    _context = {}
    
    def __init__(self, **kwargs):
        self.context = kwargs
    
    def __enter__(self):
        LogContext._context.update(self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Remove only the keys we added
        for key in self.context:
            LogContext._context.pop(key, None)


def get_log_context() -> dict:
    """Get current logging context."""
    return LogContext._context.copy()


def clear_log_context():
    """Clear all logging context."""
    LogContext._context.clear()


# ============================================================================
# Custom Logger Adapter
# ============================================================================

class StructuredLogger(logging.Logger):
    """
    Custom logger that automatically adds context to all log entries.
    """
    
    def makeRecord(self, name, level, fn, lno, msg, args, exc_info, extra=None, sinfo=None):
        # Add context to extra
        if extra is None:
            extra = {}
        
        # Include log context
        context = get_log_context()
        for key, value in context.items():
            if key not in extra:
                extra[key] = value
        
        # Add latency_ms if set in context and not in extra
        if "latency_ms" in context and "latency_ms" not in extra:
            extra["latency_ms"] = context["latency_ms"]
        
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, extra, sinfo)


# ============================================================================
# Utility Functions
# ============================================================================

def hash_message(message: str) -> str:
    """
    Create a short hash of a user message for logging without storing PII.
    
    Args:
        message: The user's message
        
    Returns:
        8-character hex hash
    """
    return hashlib.sha256(message.encode()).hexdigest()[:8]


def setup_logging(name: str = "chatbotura") -> logging.Logger:
    """
    Setup and configure structured logging.
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Use custom StructuredLogger class
    logger.__class__ = StructuredLogger
    
    # Console handler with JSON formatter
    handler = StreamHandler(sys.stdout)
    handler.setFormatter(StructuredLogFormatter())
    logger.addHandler(handler)
    
    # Propagate to root for library logs
    logger.propagate = False
    
    return logger


def get_logger(name: str = "chatbotura") -> logging.Logger:
    """
    Get or create a structured logger.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    
    # Initialize if not already set up
    if not logger.handlers or logger.level == logging.NOTSET:
        return setup_logging(name)
    
    return logger


# ============================================================================
# Convenience Logging Functions
# ============================================================================

def log_request(
    logger: logging.Logger,
    tenant_id: str,
    session_id: Optional[str],
    user_message: str,
    latency_ms: float,
    status: str = "success"
):
    """
    Log a chat request with full context.
    
    Args:
        logger: The logger instance
        tenant_id: Tenant identifier
        session_id: Session identifier (optional)
        user_message: User's message
        latency_ms: Request latency in milliseconds
        status: Request status (success/error)
    """
    with LogContext(
        tenant_id=tenant_id,
        session_id=session_id,
        user_message_hash=hash_message(user_message),
        latency_ms=latency_ms,
        request_status=status
    ):
        logger.info(f"Chat request completed: {status}")


def log_error(
    logger: logging.Logger,
    error: Exception,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    context: Optional[dict] = None
):
    """
    Log an error with full context.
    
    Args:
        logger: The logger instance
        error: The exception
        tenant_id: Tenant identifier (optional)
        session_id: Session identifier (optional)
        context: Additional context dict
    """
    extra = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    if tenant_id:
        extra["tenant_id"] = tenant_id
    if session_id:
        extra["session_id"] = session_id
    if context:
        extra.update(context)
    
    with LogContext(**extra):
        logger.error(f"Error: {error}", exc_info=True)


# ============================================================================
# Initialize Default Logger
# ============================================================================

# Setup default logger at module import
default_logger = setup_logging("chatbotura")