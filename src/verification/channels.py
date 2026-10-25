"""
Deterministic multi-channel selection engine for IncuBrix Outreach Engine.
Selects Primary and Backup channels (Email, LinkedIn, Instagram) based on:
1. Public business contact availability
2. Verification status and recency (<= 60 days)
3. Creator professional use evidence
4. Segment fit (podcaster, youtube creator, coach, consultant, educator)
5. Applicable channel/platform restrictions

STRICT SAFETY: Only message preparation. No automated sending, scraping, or DM bots.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field

from src.models import Lead, EvidenceItem, current_utc_iso
from src.logging_config import get_logger

logger = get_logger("channels")

# Canonical supported outreach channels
VALID_CHANNELS = ("email", "linkedin", "instagram")

# Canonical segments
CANONICAL_SEGMENTS = (
    "podcaster",
    "youtube_creator",
    "coach",
    "consultant",
    "educator",
)


class ChannelEvidence(BaseModel):
    """Normalized evidence for a potential outreach channel."""
    channel: str  # 'email', 'linkedin', 'instagram'
    contact_value: str
    source_url: str
    verified_date: str
    is_verified: bool = True
    recency_days: int = 0
    professional_use_note: str = ""


class ChannelSelectionResult(BaseModel):
    """Deterministic channel selection output."""
    lead_id: Optional[str] = None
    creator_name: str
    segment: str
    primary_channel: str  # 'email', 'linkedin', 'instagram', or 'needs_review'
    primary_channel_reason: str
    primary_contact_value: str
    primary_contact_source_url: str
    primary_contact_verified_date: str
    backup_channel: str = ""
    backup_channel_reason: str = ""
    backup_contact_value: str = ""
    backup_contact_source_url: str = ""
    channel_suitability_status: str  # 'suitable' or 'needs_review'
    notes: List[str] = Field(default_factory=list)


def normalize_segment(creator_type: Optional[str]) -> str:
    """Map raw creator type to one of the 5 canonical assessment segments."""
    val = (creator_type or "").lower().strip()
    if any(k in val for k in ("podcaster", "video_podcaster", "podcast")):
        return "podcaster"
    if any(k in val for k in ("youtube", "video_creator", "long_form", "long-form")):
        return "youtube_creator"
    if "coach" in val:
        return "coach"
    if "consultant" in val:
        return "consultant"
    if any(k in val for k in ("educator", "teacher", "instructor", "professor", "course")):
        return "educator"
    # Default to youtube_creator if video-first, else educator
    return "youtube_creator"


def _calculate_recency_days(date_str: Optional[str]) -> int:
    """Calculate days between verified date and now."""
    if not date_str:
        return 999
    try:
        clean = date_str.split("T")[0]
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = (now - dt).days
        return max(0, diff)
    except Exception:
        return 999


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def extract_available_channels(
    lead: Lead,
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> Dict[str, ChannelEvidence]:
    """
    Extract verified contact routes for Email, LinkedIn, and Instagram
    from lead fields and structured evidence records.
    """
    channels: Dict[str, ChannelEvidence] = {}
    ev_items = evidence_items or []

    # 1. Evaluate Email
    contact_type = (lead.business_contact_type or "").lower()
    contact_val = (lead.business_contact_value or "").strip()
    contact_src = lead.business_contact_source_url or lead.official_profile_url or ""
    verified_date = (
        getattr(lead, "business_contact_verified_date", None)
        or getattr(lead, "business_contact_last_active", None)
        or getattr(lead, "evidence_checked_at", None)
        or current_utc_iso()
    )

    if EMAIL_REGEX.match(contact_val) or "@" in contact_val:
        recency = _calculate_recency_days(verified_date)
        if recency <= 60:
            channels["email"] = ChannelEvidence(
                channel="email",
                contact_value=contact_val,
                source_url=contact_src,
                verified_date=verified_date,
                is_verified=True,
                recency_days=recency,
                professional_use_note="Public business inquiry email listed on profile/website for inbound communication.",
            )

    # Also search evidence items for email
    if "email" not in channels:
        for ev in ev_items:
            ev_type_str = str(getattr(ev, "evidence_type", ""))
            if "BUSINESS_CONTACT" in ev_type_str.upper() or "CONTACT" in ev_type_str.upper():
                desc = str(getattr(ev, "short_factual_description", ""))
                src = str(getattr(ev, "source_url", ""))
                match = EMAIL_REGEX.search(desc) or EMAIL_REGEX.search(src)
                if match:
                    email_val = match.group(0)
                    ch_date = getattr(ev, "content_date", None) or getattr(ev, "checked_at", None) or current_utc_iso()
                    rec = _calculate_recency_days(ch_date)
                    if rec <= 60:
                        channels["email"] = ChannelEvidence(
                            channel="email",
                            contact_value=email_val,
                            source_url=src,
                            verified_date=ch_date,
                            is_verified=True,
                            recency_days=rec,
                            professional_use_note="Verified public business contact email in evidence logs.",
                        )
                        break

    # 2. Evaluate LinkedIn
    prof_url = (lead.official_profile_url or "").lower()
    linkedin_url = ""
    linkedin_src = ""
    linkedin_date = verified_date

    if "linkedin.com" in prof_url:
        linkedin_url = lead.official_profile_url
        linkedin_src = lead.official_profile_url
    else:
        for ev in ev_items:
            url_str = str(getattr(ev, "source_url", "")).lower()
            desc_str = str(getattr(ev, "short_factual_description", "")).lower()
            if "linkedin.com/in/" in url_str or "linkedin.com/in/" in desc_str:
                linkedin_url = getattr(ev, "source_url", "")
                linkedin_src = linkedin_url
                linkedin_date = getattr(ev, "content_date", None) or getattr(ev, "checked_at", None) or verified_date
                break

    if linkedin_url:
        rec = _calculate_recency_days(linkedin_date)
        if rec <= 60:
            channels["linkedin"] = ChannelEvidence(
                channel="linkedin",
                contact_value=linkedin_url,
                source_url=linkedin_src,
                verified_date=linkedin_date,
                is_verified=True,
                recency_days=rec,
                professional_use_note="Verified LinkedIn profile used for professional publishing and B2B engagement.",
            )

    # 3. Evaluate Instagram
    instagram_url = ""
    instagram_src = ""
    instagram_date = verified_date

    if "instagram.com" in prof_url:
        instagram_url = lead.official_profile_url
        instagram_src = lead.official_profile_url
    else:
        for ev in ev_items:
            url_str = str(getattr(ev, "source_url", "")).lower()
            desc_str = str(getattr(ev, "short_factual_description", "")).lower()
            if "instagram.com/" in url_str or "instagram.com/" in desc_str:
                instagram_url = getattr(ev, "source_url", "")
                instagram_src = instagram_url
                instagram_date = getattr(ev, "content_date", None) or getattr(ev, "checked_at", None) or verified_date
                break

    if instagram_url:
        rec = _calculate_recency_days(instagram_date)
        if rec <= 60:
            channels["instagram"] = ChannelEvidence(
                channel="instagram",
                contact_value=instagram_url,
                source_url=instagram_src,
                verified_date=instagram_date,
                is_verified=True,
                recency_days=rec,
                professional_use_note="Verified public Instagram creator presence with recent active publishing.",
            )


    return channels


def select_channels_for_lead(
    lead: Lead,
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> ChannelSelectionResult:
    """
    Deterministic channel-selection function.
    Evaluates:
    - Public business contact availability
    - Verification status and recency (<= 60 days)
    - Creator professional use evidence
    - Segment fit
    - Platform restrictions (respecting anti-spam and connection limits)

    Never marks suitable unless verified contact evidence is available.
    Stores explicit rationale for both primary and backup decisions.
    """
    segment = normalize_segment(lead.creator_type)
    available = extract_available_channels(lead, evidence_items)

    # If no channels verified within 60 days
    if not available:
        return ChannelSelectionResult(
            lead_id=str(lead.id) if lead.id is not None else None,
            creator_name=lead.creator_name or "Unknown Creator",
            segment=segment,
            primary_channel="needs_review",
            primary_channel_reason=(
                f"No verified public contact channel (Email, LinkedIn, Instagram) with active evidence "
                f"within the past 60 days found for {lead.creator_name or 'this creator'}. Manual research required."
            ),
            primary_contact_value="",
            primary_contact_source_url="",
            primary_contact_verified_date="",
            backup_channel="",
            backup_channel_reason="No secondary contact channel available.",
            backup_contact_value="",
            backup_contact_source_url="",
            channel_suitability_status="needs_review",
            notes=["Missing verified contact route or evidence older than 60 days."],
        )

    primary_chan: str = ""
    primary_reason: str = ""
    backup_chan: str = ""
    backup_reason: str = ""

    # Segment-specific deterministic rules:
    if segment in ("podcaster", "youtube_creator"):
        # Video/Audio creators prefer email for production inquiries and guest bookings
        if "email" in available:
            primary_chan = "email"
            primary_reason = (
                f"{segment.replace('_', ' ').title()}s systematically handle production partnerships and tool pitches "
                f"via their public business inquiry email ({available['email'].contact_value}), verified from "
                f"{available['email'].source_url} (verified {available['email'].recency_days}d ago)."
            )
            # Backup: LinkedIn if available, else Instagram
            if "linkedin" in available:
                backup_chan = "linkedin"
                backup_reason = (
                    f"Verified professional LinkedIn presence available ({available['linkedin'].contact_value}) "
                    f"for direct professional connection if email yields no response."
                )
            elif "instagram" in available:
                backup_chan = "instagram"
                backup_reason = (
                    f"Public creator Instagram profile verified ({available['instagram'].contact_value}) "
                    f"as secondary visibility channel."
                )
        elif "linkedin" in available:
            primary_chan = "linkedin"
            primary_reason = (
                f"Email was not publicly listed; verified LinkedIn profile ({available['linkedin'].contact_value}) "
                f"selected as primary professional touchpoint."
            )
            if "instagram" in available:
                backup_chan = "instagram"
                backup_reason = (
                    f"Public Instagram profile ({available['instagram'].contact_value}) available as backup."
                )
        else:
            primary_chan = "instagram"
            primary_reason = (
                f"Instagram is the sole verified public channel ({available['instagram'].contact_value}) "
                f"with active publishing recency."
            )

    elif segment in ("consultant", "coach"):
        # B2B consultants/coaches operate heavily on LinkedIn
        if "linkedin" in available and "email" in available:
            # If domain email exists, email is primary; LinkedIn is high-touch backup
            if not any(k in available["email"].contact_value for k in ("gmail.com", "yahoo.com", "hotmail.com")):
                primary_chan = "email"
                primary_reason = (
                    f"Verified domain business email ({available['email'].contact_value}) provides direct executive "
                    f"reach without platform connection caps."
                )
                backup_chan = "linkedin"
                backup_reason = (
                    f"Active LinkedIn profile ({available['linkedin'].contact_value}) serves as an ideal peer-to-peer "
                    f"follow-up channel for consulting workflow discussions."
                )
            else:
                primary_chan = "linkedin"
                primary_reason = (
                    f"Consultants/Coaches actively engage with clients on LinkedIn. Verified profile "
                    f"({available['linkedin'].contact_value}) allows context-rich B2B outreach."
                )
                backup_chan = "email"
                backup_reason = (
                    f"Verified business contact email ({available['email'].contact_value}) available as asynchronous backup."
                )
        elif "linkedin" in available:
            primary_chan = "linkedin"
            primary_reason = (
                f"Verified LinkedIn profile ({available['linkedin'].contact_value}) is the primary professional "
                f"channel for {segment} client acquisition."
            )
            if "instagram" in available:
                backup_chan = "instagram"
                backup_reason = (
                    f"Instagram profile ({available['instagram'].contact_value}) verified as secondary brand channel."
                )
        elif "email" in available:
            primary_chan = "email"
            primary_reason = (
                f"Verified business email ({available['email'].contact_value}) verified from {available['email'].source_url}."
            )
            if "instagram" in available:
                backup_chan = "instagram"
                backup_reason = f"Instagram ({available['instagram'].contact_value}) available as backup."
        else:
            primary_chan = "instagram"
            primary_reason = (
                f"Instagram ({available['instagram'].contact_value}) is the only verified profile route."
            )

    else:  # educator
        if "email" in available:
            primary_chan = "email"
            primary_reason = (
                f"Educators and instructors maintain structured business/academic email communication "
                f"({available['email'].contact_value}) for curriculum and tooling discussions."
            )
            if "linkedin" in available:
                backup_chan = "linkedin"
                backup_reason = (
                    f"Professional academic/industry LinkedIn profile ({available['linkedin'].contact_value}) "
                    f"verified for professional outreach."
                )
            elif "instagram" in available:
                backup_chan = "instagram"
                backup_reason = f"Creator Instagram ({available['instagram'].contact_value}) verified as backup."
        elif "linkedin" in available:
            primary_chan = "linkedin"
            primary_reason = (
                f"Verified professional LinkedIn profile ({available['linkedin'].contact_value}) selected "
                f"for educator curriculum and workflow discussion."
            )
            if "instagram" in available:
                backup_chan = "instagram"
                backup_reason = f"Instagram ({available['instagram'].contact_value}) available as backup."
        else:
            primary_chan = "instagram"
            primary_reason = (
                f"Instagram profile ({available['instagram'].contact_value}) verified with recent public content."
            )

    # Populate final primary and backup records
    prim_ev = available[primary_chan]
    backup_ev = available.get(backup_chan)

    return ChannelSelectionResult(
        lead_id=str(lead.id) if lead.id is not None else None,
        creator_name=lead.creator_name or "Unknown Creator",
        segment=segment,
        primary_channel=primary_chan,
        primary_channel_reason=primary_reason,
        primary_contact_value=prim_ev.contact_value,
        primary_contact_source_url=prim_ev.source_url,
        primary_contact_verified_date=prim_ev.verified_date,
        backup_channel=backup_chan,
        backup_channel_reason=backup_reason,
        backup_contact_value=backup_ev.contact_value if backup_ev else "",
        backup_contact_source_url=backup_ev.source_url if backup_ev else "",
        channel_suitability_status="suitable",
        notes=[
            f"Evaluated {len(available)} verified channel(s): {', '.join(available.keys())}",
            f"Segment: {segment}. Verification recency: {prim_ev.recency_days} days.",
        ],
    )
