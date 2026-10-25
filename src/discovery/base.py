"""
Abstract base class for creator candidate discovery sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.models import Lead


class BaseDiscovery(ABC):
    """Abstract interface for discovery adapters (CSV, YouTube API, etc.)."""

    def __init__(self, source_name: str):
        self.source_name = source_name

    @abstractmethod
    def discover(self, **kwargs: Any) -> List[Lead]:
        """
        Discover candidate leads from the source.
        Discovered candidates are returned with qualification_status='discovered'.
        Missing evidence must remain missing (None or empty).
        """
        pass
