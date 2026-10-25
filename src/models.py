"""
Pydantic data models for IncuBrix Lead Discovery and Qualification Engine.
Adheres strictly to the assessment requirements:
- Missing evidence is represented as None/empty, never guessed or fabricated.
- Distinguishes candidates from qualified leads.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QualificationStatus(str, Enum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class PriorityLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"


def current_utc_iso() -> str:
    """Return current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class Lead(BaseModel):
    """
    Core Lead and Candidate data model.
    A newly discovered creator starts with qualification_status='discovered'.
    Only after passing all verification hard gates does status become 'qualified'.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    # Optional internal database ID
    id: Optional[int] = None

    # Required Creator & Platform Identifiers
    creator_name: str
    creator_type: str
    country: Optional[str] = None
    language: Optional[str] = "English"
    platform: str
    platform_id: str
    official_profile_url: str
    candidate_source_url: str

    # Activity & Content History (Missing represented as empty lists, never fabricated)
    recent_content_urls: List[str] = Field(default_factory=list)
    recent_content_dates: List[str] = Field(default_factory=list)

    # Qualification Evidence (Missing represented as None, never guessed)
    commercial_evidence_url: Optional[str] = None
    workflow_need_evidence_url: Optional[str] = None
    business_contact_type: Optional[str] = None
    business_contact_value: Optional[str] = None
    business_contact_source_url: Optional[str] = None
    business_contact_last_active: Optional[str] = None
    evidence_checked_at: Optional[str] = None

    # Qualification Decision & Scoring
    qualification_status: str = QualificationStatus.DISCOVERED.value
    disqualification_reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
    priority: Optional[str] = None

    # Audit & Tracking Timestamps
    first_discovered_at: str = Field(default_factory=current_utc_iso)
    last_checked_at: Optional[str] = None
    last_run_id: Optional[str] = None

    @field_validator("first_discovered_at", mode="before")
    @classmethod
    def default_first_discovered(cls, v: Any) -> str:
        """Default first_discovered_at to current UTC ISO timestamp if None or empty."""
        if v is None:
            return current_utc_iso()
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in ("none", "null", "nan"):
                return current_utc_iso()
            return s
        return str(v)

    @field_validator(
        "country",
        "commercial_evidence_url",
        "workflow_need_evidence_url",
        "business_contact_type",
        "business_contact_value",
        "business_contact_source_url",
        "business_contact_last_active",
        "evidence_checked_at",
        "priority",
        "last_checked_at",
        "last_run_id",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Optional[str]:
        """Convert empty strings or string 'None'/'null' to None so missing is strictly missing."""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in ("none", "null", "nan", "undefined"):
                return None
            return s
        return v

    @field_validator("recent_content_urls", "recent_content_dates", "disqualification_reasons", mode="before")
    @classmethod
    def parse_list_fields(cls, v: Any) -> List[str]:
        """Convert JSON strings or comma-delimited strings to cleanly stripped list of strings."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in ("none", "null", "[]"):
                return []
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            # Split comma separated
            return [item.strip() for item in s.split(",") if item.strip()]
        return []

    def to_db_dict(self) -> Dict[str, Any]:
        """Serialize Lead model into a dictionary suitable for SQLite insertion."""
        return {
            "id": self.id,
            "creator_name": self.creator_name,
            "creator_type": self.creator_type,
            "country": self.country,
            "language": self.language or "English",
            "platform": self.platform,
            "platform_id": self.platform_id,
            "official_profile_url": self.official_profile_url,
            "candidate_source_url": self.candidate_source_url,
            "recent_content_urls": json.dumps(self.recent_content_urls),
            "recent_content_dates": json.dumps(self.recent_content_dates),
            "commercial_evidence_url": self.commercial_evidence_url,
            "workflow_need_evidence_url": self.workflow_need_evidence_url,
            "business_contact_type": self.business_contact_type,
            "business_contact_value": self.business_contact_value,
            "business_contact_source_url": self.business_contact_source_url,
            "business_contact_last_active": self.business_contact_last_active,
            "evidence_checked_at": self.evidence_checked_at,
            "qualification_status": self.qualification_status,
            "disqualification_reasons": json.dumps(self.disqualification_reasons),
            "score": float(self.score),
            "priority": self.priority,
            "first_discovered_at": self.first_discovered_at,
            "last_checked_at": self.last_checked_at,
            "last_run_id": self.last_run_id,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Lead:
        """Construct a Lead instance from an SQLite row dictionary."""
        data = dict(row)
        for list_col in ("recent_content_urls", "recent_content_dates", "disqualification_reasons"):
            val = data.get(list_col)
            if isinstance(val, str) and val.strip().startswith("["):
                try:
                    data[list_col] = json.loads(val)
                except Exception:
                    data[list_col] = []
            elif val is None:
                data[list_col] = []
        return cls(**data)


class VerificationLog(BaseModel):
    """Audit log entry for candidate verification events."""
    id: Optional[int] = None
    lead_id: Optional[int] = None
    platform: str
    platform_id: str
    action: str  # e.g., "qualify", "import", "merge", "reject"
    status_before: Optional[str] = None
    status_after: Optional[str] = None
    disqualification_reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
    priority: Optional[str] = None
    timestamp: str = Field(default_factory=current_utc_iso)
    run_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "platform": self.platform,
            "platform_id": self.platform_id,
            "action": self.action,
            "status_before": self.status_before,
            "status_after": self.status_after,
            "disqualification_reasons": json.dumps(self.disqualification_reasons),
            "score": self.score,
            "priority": self.priority,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "details": json.dumps(self.details),
        }
