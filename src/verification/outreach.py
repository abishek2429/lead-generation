"""
Personalised outreach preparation engine for IncuBrix Lead Engine.
Generates compliant, source-grounded outreach copy for Qualified & Priority A leads:
- Selects Primary and Backup channels (Email, LinkedIn, Instagram) deterministically.
- Validates that public evidence supports the channel and a verified recent content item exists.
- Generates 3 touches (First message, Follow-up 1 [+3d], Follow-up 2 [+7d]) tailored by creator segment.
- Identifies sender honestly as an assessment candidate, never an employee.
- Avoids fabricated observations, promises of virality, or claims of prior relationships.
- STRICT SAFETY: No automated sending or DM bots. Message preparation only.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from src.logging_config import get_logger
from src.models import Lead, EvidenceItem, OutreachPreparation, current_utc_iso
from src.verification.channels import (
    select_channels_for_lead,
    ChannelSelectionResult,
    normalize_segment,
)
from src.verification.templates import (
    get_all_templates,
    render_touch,
    validate_lead_personalisation_evidence,
    get_opt_out_footer_for_channel,
    SENDER_IDENTITY,
    EMAIL_OPT_OUT,
)

logger = get_logger("outreach")

COMPLIANT_OPT_OUT_FOOTER = EMAIL_OPT_OUT


def generate_outreach_for_lead(
    lead: Lead,
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> OutreachPreparation:
    """
    Generate personalised, grounded outreach preparation for an eligible lead.
    Must cite an actual recent content item and verified public contact route.
    If evidence is insufficient, marks 'needs_review' and avoids generating fake copy.
    """
    # 1. Deterministic channel selection
    channel_res = select_channels_for_lead(lead, evidence_items)

    # 2. Evidence validation
    is_valid, content_url, failure_explanation = validate_lead_personalisation_evidence(lead, channel_res)

    creator_name = lead.creator_name or "Creator"
    segment = channel_res.segment
    primary_chan = channel_res.primary_channel
    opt_out_text = get_opt_out_footer_for_channel(primary_chan)

    if not is_valid or channel_res.channel_suitability_status == "needs_review":
        # Evidence is insufficient: do not generate a supposedly personalised message
        unpersonalised_notice = (
            f"[OUTREACH PERSONALISATION SUPPRESSED]\n"
            f"Reason: {failure_explanation or channel_res.primary_channel_reason}\n"
            f"Lead ID: {lead.id} ({creator_name})\n"
            f"Manual verification required before outreach generation."
        )
        rationale = (
            f"Lead flagged as 'needs_review'. Insufficient verified contact or content evidence "
            f"within 60 days. Missing: {failure_explanation or channel_res.primary_channel_reason}"
        )
        return OutreachPreparation(
            lead_id=lead.id,
            platform_id=lead.platform_id,
            creator_name=creator_name,
            score=float(lead.score),
            priority=lead.priority or "A",
            segment=segment,
            primary_channel=channel_res.primary_channel,
            primary_channel_reason=channel_res.primary_channel_reason,
            primary_contact_value=channel_res.primary_contact_value,
            primary_contact_source_url=channel_res.primary_contact_source_url,
            primary_contact_verified_date=channel_res.primary_contact_verified_date,
            backup_channel=channel_res.backup_channel,
            backup_channel_reason=channel_res.backup_channel_reason,
            backup_contact_value=channel_res.backup_contact_value,
            backup_contact_source_url=channel_res.backup_contact_source_url,
            channel_suitability_status="needs_review",
            subject_line=f"[Review Needed] Outreach preparation for {creator_name}",
            proposed_first_message=unpersonalised_notice,
            follow_up_1="",
            follow_up_2="",
            follow_up_1_delay_days=3,
            follow_up_2_delay_days=7,
            chosen_channel=channel_res.primary_channel,
            specific_content_source_url=content_url or lead.official_profile_url or "",
            personalisation_rationale=rationale,
            opt_out_language=opt_out_text,
            sender_identity=SENDER_IDENTITY,
            validation_status="needs_review",
            validation_notes=failure_explanation or channel_res.primary_channel_reason,
            outreach_status="DRAFT",
            created_at=current_utc_iso(),
            is_synthetic=getattr(lead, "is_synthetic", False),
        )

    # 3. Retrieve templates for segment & primary channel
    templates = get_all_templates()
    t1 = next(
        (t for t in templates if t.segment == segment and t.channel == primary_chan and t.touch_number == 1),
        None,
    )
    t2 = next(
        (t for t in templates if t.segment == segment and t.channel == primary_chan and t.touch_number == 2),
        None,
    )
    t3 = next(
        (t for t in templates if t.segment == segment and t.channel == primary_chan and t.touch_number == 3),
        None,
    )

    # Fallback to youtube_creator / email if somehow missing
    if not t1:
        t1 = next((t for t in templates if t.segment == "youtube_creator" and t.channel == "email" and t.touch_number == 1), None)
    if not t2:
        t2 = next((t for t in templates if t.segment == "youtube_creator" and t.channel == "email" and t.touch_number == 2), None)
    if not t3:
        t3 = next((t for t in templates if t.segment == "youtube_creator" and t.channel == "email" and t.touch_number == 3), None)

    subj_1, msg_1 = render_touch(t1, lead, channel_res, content_url)
    _, msg_2 = render_touch(t2, lead, channel_res, content_url)
    _, msg_3 = render_touch(t3, lead, channel_res, content_url)

    rationale = (
        f"Targeted as a verified {segment.replace('_', ' ').title()} ({creator_name}) publishing actively on {lead.platform}. "
        f"First message grounded in verified recent content item ({content_url}). "
        f"Primary channel selected: {channel_res.primary_channel.upper()} ({channel_res.primary_channel_reason}). "
        f"Backup channel: {channel_res.backup_channel.upper() if channel_res.backup_channel else 'None'} ({channel_res.backup_channel_reason}). "
        f"Sender honestly identified as assessment candidate. Opt-out language included."
    )

    return OutreachPreparation(
        lead_id=lead.id,
        platform_id=lead.platform_id,
        creator_name=creator_name,
        score=float(lead.score),
        priority=lead.priority or "A",
        segment=segment,
        primary_channel=channel_res.primary_channel,
        primary_channel_reason=channel_res.primary_channel_reason,
        primary_contact_value=channel_res.primary_contact_value,
        primary_contact_source_url=channel_res.primary_contact_source_url,
        primary_contact_verified_date=channel_res.primary_contact_verified_date,
        backup_channel=channel_res.backup_channel,
        backup_channel_reason=channel_res.backup_channel_reason,
        backup_contact_value=channel_res.backup_contact_value,
        backup_contact_source_url=channel_res.backup_contact_source_url,
        channel_suitability_status="suitable",
        subject_line=subj_1,
        proposed_first_message=msg_1,
        follow_up_1=msg_2,
        follow_up_2=msg_3,
        follow_up_1_delay_days=3,
        follow_up_2_delay_days=7,
        chosen_channel=f"{channel_res.primary_channel}: {channel_res.primary_contact_value}",
        specific_content_source_url=content_url,
        personalisation_rationale=rationale,
        opt_out_language=opt_out_text,
        sender_identity=SENDER_IDENTITY,
        validation_status="valid",
        validation_notes="Grounded in verified recent content URL and verified public contact route.",
        outreach_status="DRAFT",
        created_at=current_utc_iso(),
        is_synthetic=getattr(lead, "is_synthetic", False),
    )


def prepare_all_qualified_outreach(
    leads: List[Lead],
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> List[OutreachPreparation]:
    """
    Generate personalised outreach preparations for all qualified leads.
    """
    qualified_leads = [
        l for l in leads
        if (l.qualification_status or "").lower() == "qualified"
    ]
    qualified_leads.sort(key=lambda x: (x.priority or "C", -float(x.score or 0)))

    ev_by_lead: Dict[int, List[EvidenceItem]] = {}
    if evidence_items:
        for ev in evidence_items:
            ev_by_lead.setdefault(ev.lead_id, []).append(ev)

    preps = []
    for lead in qualified_leads:
        lead_ev = ev_by_lead.get(lead.id, []) if lead.id else []
        prep = generate_outreach_for_lead(lead, lead_ev)
        preps.append(prep)

    logger.info(f"Generated outreach preparations for {len(preps)} qualified leads.")
    return preps


def prepare_priority_a_outreach_batch(
    leads: List[Lead],
    max_count: int = 25,
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> List[OutreachPreparation]:
    """
    Prepare personalised outreach sequences for eligible Priority A leads.
    Only processes leads that are qualified and assigned Priority A.
    Caps at max_count (default 25) without forcing unqualified records.
    """
    priority_a_leads = [
        l for l in leads
        if (l.priority or "").upper() == "A"
        and (l.qualification_status or "").lower() == "qualified"
    ]
    # Sort by score descending
    priority_a_leads.sort(key=lambda x: float(x.score or 0), reverse=True)
    selected = priority_a_leads[:max_count]

    ev_by_lead: Dict[int, List[EvidenceItem]] = {}
    if evidence_items:
        for ev in evidence_items:
            ev_by_lead.setdefault(ev.lead_id, []).append(ev)

    preps = []
    for lead in selected:
        lead_ev = ev_by_lead.get(lead.id, []) if lead.id else []
        preps.append(generate_outreach_for_lead(lead, lead_ev))

    logger.info(f"Generated {len(preps)} personalised outreach preparations for Priority A leads.")
    return preps
