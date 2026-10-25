"""
Evidence and verification gate validation utilities.
Checks compliance with Day 1 qualification policy:
- Missing evidence is treated strictly as missing.
- Verification timestamps and sources are validated.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel

URL_REGEX = re.compile(
    r"^https?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain...
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


def is_valid_url(url: Optional[str]) -> bool:
    """Validate whether URL string has valid scheme, host, and structure."""
    if not url or not isinstance(url, str):
        return False
    trimmed = url.strip()
    if not trimmed:
        return False
    return bool(URL_REGEX.match(trimmed))


def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO date or standard YYYY-MM-DD string into UTC datetime."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.strip()
    if not cleaned:
        return None
    # Handle YYYY-MM-DD
    if len(cleaned) == 10 and cleaned.count("-") == 2:
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        # Replace trailing Z with +00:00 for fromisoformat compatibility
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def calculate_days_ago(date_str: Optional[str], reference_date: Optional[datetime] = None) -> Optional[int]:
    """Calculate elapsed days between given date string and reference date."""
    dt = parse_iso_date(date_str)
    if dt is None:
        return None
    if isinstance(reference_date, str):
        ref = parse_iso_date(reference_date) or datetime.now(timezone.utc)
    else:
        ref = reference_date or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    diff = (ref - dt).total_seconds() / 86400.0
    return max(0, int(diff))


class GateResult(BaseModel):
    gate_name: str
    passed: bool
    reason: Optional[str] = None
