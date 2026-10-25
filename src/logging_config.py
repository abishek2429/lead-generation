"""
Structured logging configuration for IncuBrix Lead Discovery Engine.
Provides consistent formatting across CLI runs, background jobs, and Streamlit.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def generate_run_id(prefix: str = "run") -> str:
    """Generate a stable, unique, time-sortable run identifier."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uid = uuid.uuid4().hex[:6]
    return f"{prefix}_{now_str}_{short_uid}"


import re

SECRET_PATTERN = re.compile(r"(key|token|secret|password|api_key)=([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z-_]{20,40}")


class SecretMaskingFilter(logging.Filter):
    """Filter that redacts API keys, tokens, and query parameter secrets from all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = API_KEY_PATTERN.sub("***REDACTED_API_KEY***", record.msg)
            record.msg = SECRET_PATTERN.sub(r"\1=***REDACTED***", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                sanitized = {}
                for k, v in record.args.items():
                    val_str = str(v)
                    val_str = API_KEY_PATTERN.sub("***REDACTED_API_KEY***", val_str)
                    sanitized[k] = SECRET_PATTERN.sub(r"\1=***REDACTED***", val_str)
                record.args = sanitized
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    SECRET_PATTERN.sub(
                        r"\1=***REDACTED***",
                        API_KEY_PATTERN.sub("***REDACTED_API_KEY***", str(arg)),
                    )
                    for arg in record.args
                )
        return True


class StructuredFormatter(logging.Formatter):
    """Custom formatter producing readable structured logs with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        run_id = getattr(record, "run_id", "-")
        creator = getattr(record, "creator", "-")
        base_msg = super().format(record)
        # Final pass redaction on formatted message
        redacted_msg = API_KEY_PATTERN.sub("***REDACTED_API_KEY***", base_msg)
        redacted_msg = SECRET_PATTERN.sub(r"\1=***REDACTED***", redacted_msg)
        return f"[{timestamp}] [{record.levelname:<7}] [run:{run_id}] [creator:{creator}] {record.name}: {redacted_msg}"


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = "data/app.log",
) -> logging.Logger:
    """Configure root logger with console and optional file handlers."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger("incubrix")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates during reload
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    secret_filter = SecretMaskingFilter()
    root_logger.addFilter(secret_filter)

    formatter = StructuredFormatter("%(message)s")

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(secret_filter)
    root_logger.addHandler(console_handler)

    # File Handler
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(secret_filter)
            root_logger.addHandler(file_handler)
        except Exception as exc:
            print(f"Warning: Could not configure log file {log_file}: {exc}", file=sys.stderr)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger under the 'incubrix' hierarchy."""
    if not name.startswith("incubrix"):
        name = f"incubrix.{name}"
    return logging.getLogger(name)
