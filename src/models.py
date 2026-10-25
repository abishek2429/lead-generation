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
    NEEDS_REVIEW = "needs_review"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class PriorityLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class EvidenceType(str, Enum):
    OFFICIAL_IDENTITY = "official_identity"
    RECENT_CONTENT = "recent_content"
    COMMERCIAL_OFFER = "commercial_offer"
    WORKFLOW_NEED = "workflow_need"
    BUSINESS_CONTACT = "business_contact"
    CONTACT_ACTIVITY = "contact_activity"
    COUNTRY_LANGUAGE = "country_language"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    STALE = "stale"


class VerificationMethod(str, Enum):
    AUTOMATED_API = "automated_api"
    PUBLIC_HTTP_CHECK = "public_http_check"
    DOMAIN_INSPECTION = "domain_inspection"
    HUMAN_REVIEW = "human_review"


def current_utc_iso() -> str:
    """Return current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class EvidenceItem(BaseModel):
    """
    Source-linked evidence item representing an audited claim.
    Never labeled verified merely because a URL exists.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: Optional[int] = None
    lead_id: Optional[int] = None
    platform: str
    platform_id: str
    evidence_type: str
    source_url: str
    short_factual_description: str
    content_date: Optional[str] = None
    checked_at: str = Field(default_factory=current_utc_iso)
    verification_status: str = VerificationStatus.UNVERIFIED.value
    verification_method: str = VerificationMethod.PUBLIC_HTTP_CHECK.value
    review_reason: Optional[str] = None

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "platform": self.platform,
            "platform_id": self.platform_id,
            "evidence_type": self.evidence_type,
            "source_url": self.source_url,
            "short_factual_description": self.short_factual_description,
            "content_date": self.content_date,
            "checked_at": self.checked_at,
            "verification_status": self.verification_status,
            "verification_method": self.verification_method,
            "review_reason": self.review_reason,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> EvidenceItem:
        return cls(**dict(row))


class OutreachPreparation(BaseModel):
    """
    Personalised multi-channel outreach preparation for qualified leads.
    Grounded in specific recent content and verified business contact.
    Identifies sender honestly as an assessment candidate.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: Optional[int] = None
    lead_id: Optional[int] = None
    platform_id: str
    creator_name: str
    score: float = 0.0
    priority: str = "A"
    segment: Optional[str] = None

    # Channel decision & verification evidence
    primary_channel: str = "email"
    primary_channel_reason: str = ""
    primary_contact_value: str = ""
    primary_contact_source_url: str = ""
    primary_contact_verified_date: Optional[str] = None

    backup_channel: Optional[str] = None
    backup_channel_reason: Optional[str] = None
    backup_contact_value: Optional[str] = None
    backup_contact_source_url: Optional[str] = None

    channel_suitability_status: str = "suitable"  # 'suitable', 'needs_review'

    # Three-touch sequence
    subject_line: str = ""
    proposed_first_message: str = ""
    follow_up_1: str = ""
    follow_up_2: str = ""
    follow_up_1_delay_days: int = 3
    follow_up_2_delay_days: int = 7

    # Grounding & honest sender identity
    specific_content_source_url: str = ""
    personalisation_rationale: str = ""
    opt_out_language: str = ""
    sender_identity: str = "IncuBrix Growth Engineer Assessment Candidate"

    # Status & simulation tracking
    validation_status: str = "valid"  # 'valid', 'missing_evidence', 'opted_out', 'needs_review'
    validation_notes: str = ""
    outreach_status: str = "DRAFT"  # 'DRAFT', 'READY', 'SIMULATED_SENT', 'FOLLOWUP_1_DRAFT', 'FOLLOWUP_2_DRAFT', 'REPLIED', 'OPTED_OUT'

    # Backward compatibility alias
    chosen_channel: Optional[str] = None

    created_at: str = Field(default_factory=current_utc_iso)
    updated_at: Optional[str] = None
    is_synthetic: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.chosen_channel:
            if self.primary_contact_value:
                self.chosen_channel = f"{self.primary_channel}: {self.primary_contact_value}"
            else:
                self.chosen_channel = self.primary_channel
        if not self.is_synthetic:
            name = (self.creator_name or "").lower()
            val = (self.primary_contact_value or "").lower()
            pid = (self.platform_id or "").lower()
            if (
                name.startswith("[fixture]")
                or name.startswith("[synthetic")
                or "synth_yt_" in pid
                or ".synthetic.test" in val
                or val.endswith("@incubrix.local")
            ):
                self.is_synthetic = True

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "platform_id": self.platform_id,
            "creator_name": self.creator_name,
            "score": float(self.score),
            "priority": self.priority,
            "segment": self.segment or "",
            "primary_channel": self.primary_channel,
            "primary_channel_reason": self.primary_channel_reason,
            "primary_contact_value": self.primary_contact_value,
            "primary_contact_source_url": self.primary_contact_source_url,
            "primary_contact_verified_date": self.primary_contact_verified_date or "",
            "backup_channel": self.backup_channel or "",
            "backup_channel_reason": self.backup_channel_reason or "",
            "backup_contact_value": self.backup_contact_value or "",
            "backup_contact_source_url": self.backup_contact_source_url or "",
            "channel_suitability_status": self.channel_suitability_status,
            "subject_line": self.subject_line,
            "proposed_first_message": self.proposed_first_message,
            "follow_up_1": self.follow_up_1,
            "follow_up_2": self.follow_up_2,
            "follow_up_1_delay_days": self.follow_up_1_delay_days,
            "follow_up_2_delay_days": self.follow_up_2_delay_days,
            "chosen_channel": self.chosen_channel or f"{self.primary_channel}: {self.primary_contact_value}",
            "specific_content_source_url": self.specific_content_source_url,
            "personalisation_rationale": self.personalisation_rationale,
            "opt_out_language": self.opt_out_language,
            "sender_identity": self.sender_identity,
            "validation_status": self.validation_status,
            "validation_notes": self.validation_notes,
            "outreach_status": self.outreach_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "is_synthetic": 1 if self.is_synthetic else 0,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> OutreachPreparation:
        data = dict(row)
        data["is_synthetic"] = bool(data.get("is_synthetic", 0))
        # Ensure chosen_channel backward-compatibility
        if not data.get("chosen_channel"):
            p_chan = data.get("primary_channel", "email")
            p_val = data.get("primary_contact_value", "")
            data["chosen_channel"] = f"{p_chan}: {p_val}".strip(": ")
        if not data.get("primary_channel") and data.get("chosen_channel"):
            raw = str(data["chosen_channel"]).split(":")[0].strip().lower()
            data["primary_channel"] = raw if raw in ("email", "linkedin", "instagram") else "email"
        return cls(**data)


class OutreachTemplate(BaseModel):
    """
    Standard segment- and channel-specific outreach template with 3 touches.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    template_id: str
    segment: str
    channel: str
    touch_number: int
    suggested_delay_days: int
    subject_line: str
    body_template: str
    required_evidence_fields: List[str] = Field(default_factory=list)
    sender_identity: str = "IncuBrix Growth Engineer Assessment Candidate"
    compliance_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "segment": self.segment,
            "channel": self.channel,
            "touch_number": self.touch_number,
            "suggested_delay_days": self.suggested_delay_days,
            "subject_line": self.subject_line,
            "body_template": self.body_template,
            "required_evidence_fields": json.dumps(self.required_evidence_fields),
            "sender_identity": self.sender_identity,
            "compliance_notes": self.compliance_notes,
        }


class OutreachState(str, Enum):
    DRAFT = "draft"
    APPROVED_FOR_TEST = "approved_for_test"
    SENT_IN_TEST = "sent_in_test"
    REPLIED_IN_TEST = "replied_in_test"
    OPTED_OUT = "opted_out"
    CLOSED = "closed"


VALID_OUTREACH_STATES = {s.value for s in OutreachState}

VALID_STATE_TRANSITIONS: Dict[str, set[str]] = {
    OutreachState.DRAFT.value: {
        OutreachState.APPROVED_FOR_TEST.value,
        OutreachState.OPTED_OUT.value,
        OutreachState.CLOSED.value,
    },
    OutreachState.APPROVED_FOR_TEST.value: {
        OutreachState.SENT_IN_TEST.value,
        OutreachState.OPTED_OUT.value,
        OutreachState.CLOSED.value,
    },
    OutreachState.SENT_IN_TEST.value: {
        OutreachState.REPLIED_IN_TEST.value,
        OutreachState.OPTED_OUT.value,
        OutreachState.CLOSED.value,
    },
    OutreachState.REPLIED_IN_TEST.value: {
        OutreachState.CLOSED.value,
        OutreachState.OPTED_OUT.value,
    },
    OutreachState.OPTED_OUT.value: {
        OutreachState.CLOSED.value,
    },
    OutreachState.CLOSED.value: set(),  # Terminal state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal outreach simulation state transition is attempted."""
    pass


class CampaignOutreachRecord(BaseModel):
    """
    Unique outreach tracking record per lead and campaign.
    Enforces simulation state lifecycle:
    draft -> approved_for_test -> sent_in_test -> replied_in_test -> closed (or opted_out -> closed).
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: Optional[int] = None
    lead_id: int
    campaign_id: str = "default_test_campaign"
    platform_id: str
    creator_name: str
    channel: str = "email"
    contact_endpoint: str = ""
    state: str = OutreachState.DRAFT.value
    tracking_token: Optional[str] = None
    opaque_id: Optional[str] = None
    test_account_id: Optional[str] = None
    notes: Optional[str] = ""
    created_at: str = Field(default_factory=current_utc_iso)
    updated_at: Optional[str] = None
    is_synthetic: bool = False

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in VALID_OUTREACH_STATES:
            raise ValueError(f"Invalid outreach state: '{v}'. Must be one of {sorted(list(VALID_OUTREACH_STATES))}")
        return s

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "campaign_id": self.campaign_id,
            "platform_id": self.platform_id,
            "creator_name": self.creator_name,
            "channel": self.channel,
            "contact_endpoint": self.contact_endpoint,
            "state": self.state,
            "tracking_token": self.tracking_token or "",
            "opaque_id": self.opaque_id or "",
            "test_account_id": self.test_account_id or "",
            "notes": self.notes or "",
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "is_synthetic": 1 if self.is_synthetic else 0,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> CampaignOutreachRecord:
        data = dict(row)
        data["is_synthetic"] = bool(data.get("is_synthetic", 0))
        return cls(**data)


class DeliveryEvent(BaseModel):
    """
    Audit record tracking seed test delivery simulation, opens, clicks, replies, and opt-outs.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: Optional[int] = None
    lead_id: Optional[int] = None
    platform_id: str = "seed_test"
    campaign_id: str = "default_test_campaign"
    test_account_id: str = "candidate_test_account"
    idempotent_key: Optional[str] = None
    opaque_id: Optional[str] = None
    recipient_contact: str = ""
    recipient: Optional[str] = None
    creator_name: Optional[str] = None
    channel: str = "email"
    touch_number: int = 1
    event_type: str = "SENT"  # 'SENT', 'OPENED', 'CLICKED', 'REPLIED', 'OPT_OUT', 'BLOCKED', 'STATUS_CHANGE'
    status: str = "SUCCESS"  # 'SUCCESS', 'SUPPRESSED', 'FAILED'
    tracking_token: Optional[str] = None
    message_snippet: Optional[str] = None
    event_payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=current_utc_iso)
    created_at: Optional[str] = None
    is_authorized_seed: bool = True

    def model_post_init(self, __context: Any) -> None:
        if not self.recipient_contact and self.recipient:
            self.recipient_contact = self.recipient
        elif not self.recipient and self.recipient_contact:
            self.recipient = self.recipient_contact
        if not self.created_at:
            self.created_at = self.timestamp
        if self.metadata and not self.event_payload:
            self.event_payload = dict(self.metadata)
        elif self.event_payload and not self.metadata:
            self.metadata = dict(self.event_payload)

    def to_db_dict(self) -> Dict[str, Any]:
        recip = self.recipient_contact or self.recipient or ""
        payload = dict(self.event_payload or self.metadata or {})
        if self.status:
            payload["status"] = self.status
        if self.creator_name:
            payload["creator_name"] = self.creator_name
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "platform_id": self.platform_id or "seed_test",
            "campaign_id": self.campaign_id or "default_test_campaign",
            "test_account_id": self.test_account_id or "candidate_test_account",
            "idempotent_key": self.idempotent_key,
            "opaque_id": self.opaque_id or "",
            "recipient_contact": recip,
            "channel": self.channel,
            "touch_number": self.touch_number,
            "event_type": self.event_type,
            "tracking_token": self.tracking_token or "",
            "message_snippet": self.message_snippet or "",
            "event_payload": json.dumps(payload),
            "timestamp": self.timestamp,
            "is_authorized_seed": 1 if self.is_authorized_seed else 0,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> DeliveryEvent:
        data = dict(row)
        data["is_authorized_seed"] = bool(data.get("is_authorized_seed", 1))
        payload_raw = data.get("event_payload", "{}")
        payload = {}
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        data["event_payload"] = payload
        data["metadata"] = payload
        data["status"] = payload.get("status", "SUCCESS")
        data["creator_name"] = payload.get("creator_name", "")
        data["recipient"] = data.get("recipient_contact", "")
        data["created_at"] = data.get("timestamp", "")
        data["campaign_id"] = data.get("campaign_id", "default_test_campaign")
        data["test_account_id"] = data.get("test_account_id", "candidate_test_account")
        data["idempotent_key"] = data.get("idempotent_key")
        data["opaque_id"] = data.get("opaque_id")
        return cls(**data)



class SuppressionRecord(BaseModel):
    """
    Suppression list record for contacts that opted out or requested no contact.
    """
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: Optional[int] = None
    contact_value: str
    channel: str
    reason: str = "Opt-out requested"
    opted_out_at: str = Field(default_factory=current_utc_iso)

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "contact_value": self.contact_value.strip().lower(),
            "channel": self.channel,
            "reason": self.reason,
            "opted_out_at": self.opted_out_at,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> SuppressionRecord:
        return cls(**dict(row))


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
    business_contact_verified_date: Optional[str] = None
    evidence_checked_at: Optional[str] = None

    # Qualification Decision & Scoring
    qualification_status: str = QualificationStatus.DISCOVERED.value
    disqualification_reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
    priority: Optional[str] = None
    score_breakdown: Dict[str, Any] = Field(default_factory=dict)

    # Audit & Tracking Timestamps
    first_discovered_at: str = Field(default_factory=current_utc_iso)
    last_checked_at: Optional[str] = None
    last_run_id: Optional[str] = None

    # Flag for synthetic test fixtures to prevent accidental entry into real qualified exports
    is_synthetic: bool = False

    @field_validator("is_synthetic", mode="before")
    @classmethod
    def parse_bool_synthetic(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "t", "synthetic")
        return False

    def model_post_init(self, __context: Any) -> None:
        if not self.is_synthetic:
            name = (self.creator_name or "").lower()
            contact = (self.business_contact_value or "").lower()
            pid = (self.platform_id or "").lower()
            if (
                name.startswith("[fixture]")
                or name.startswith("[synthetic")
                or "synth_yt_" in pid
                or ".synthetic.test" in contact
                or contact.endswith("@incubrix.local")
            ):
                self.is_synthetic = True

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
            "score_breakdown": json.dumps(self.score_breakdown),
            "first_discovered_at": self.first_discovered_at,
            "last_checked_at": self.last_checked_at,
            "last_run_id": self.last_run_id,
            "is_synthetic": 1 if self.is_synthetic else 0,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Lead:
        """Construct a Lead instance from an SQLite row dictionary."""
        data = dict(row)
        data["is_synthetic"] = bool(data.get("is_synthetic", 0))
        for list_col in ("recent_content_urls", "recent_content_dates", "disqualification_reasons"):
            val = data.get(list_col)
            if isinstance(val, str) and val.strip().startswith("["):
                try:
                    data[list_col] = json.loads(val)
                except Exception:
                    data[list_col] = []
            elif val is None:
                data[list_col] = []

        sb_val = data.get("score_breakdown")
        if isinstance(sb_val, str) and sb_val.strip().startswith("{"):
            try:
                data["score_breakdown"] = json.loads(sb_val)
            except Exception:
                data["score_breakdown"] = {}
        elif not isinstance(sb_val, dict):
            data["score_breakdown"] = {}

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
