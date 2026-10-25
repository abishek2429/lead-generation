"""
Qualification engine enforcing Day 1 qualification policy, hard gates, and scoring rubric.
Ensures candidates are evaluated transparently without guessing missing data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.config import AppConfig, QualificationPolicy, ScoringWeights
from src.logging_config import get_logger
from src.models import Lead, QualificationStatus, VerificationLog
from src.verification.evidence import GateResult, calculate_days_ago, is_valid_url

logger = get_logger("qualification")


def classify_candidate_gates(
    lead: Lead,
    policy: QualificationPolicy,
    reference_date: Optional[datetime] = None,
) -> Tuple[str, List[str]]:
    """
    Classify creator into distinct states:
    - 'qualified': all gates passed with verified evidence
    - 'needs_review': creator matches target profile, but required commercial/workflow/contact evidence is unverified
    - 'disqualified': violates exclusionary criteria (wrong creator type, unapproved country, non-English, inactive)
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    exclusionary_reasons: List[str] = []
    missing_evidence_reasons: List[str] = []

    # 1. Segment Gate (Exclusionary)
    norm_type = (lead.creator_type or "").strip().lower()
    allowed_segments = [s.strip().lower() for s in policy.allowed_segments]
    excluded_types = [s.strip().lower() for s in policy.excluded_types]

    if norm_type in excluded_types:
        exclusionary_reasons.append(f"Excluded creator type '{lead.creator_type}' (matches excluded list)")
    elif norm_type not in allowed_segments:
        exclusionary_reasons.append(
            f"Segment '{lead.creator_type}' is not in allowed target segments: {', '.join(policy.allowed_segments)}"
        )

    # 2. Country Gate (Exclusionary if outside target; missing evidence if unknown)
    allowed_countries = [c.strip().lower() for c in policy.allowed_countries]
    lead_country = (lead.country or "").strip().lower()
    if not lead_country:
        missing_evidence_reasons.append("Missing country; creator location cannot be verified")
    elif lead_country not in allowed_countries:
        exclusionary_reasons.append(f"Country '{lead.country}' is outside the 7 approved target geographies")

    # 3. Language Gate (Exclusionary if non-English; missing if blank)
    lead_lang = (lead.language or "").strip().lower()
    target_lang = policy.primary_language.strip().lower()
    if lead_lang and lead_lang != target_lang:
        exclusionary_reasons.append(f"Language '{lead.language}' does not match primary language '{policy.primary_language}'")
    elif not lead_lang:
        missing_evidence_reasons.append("Missing language specification")

    # 4. Stable Platform ID & Official Profile URL Gate
    if not (lead.platform_id or "").strip():
        exclusionary_reasons.append("Missing stable platform_id")
    if policy.official_profile_required:
        if not lead.official_profile_url or not is_valid_url(lead.official_profile_url):
            exclusionary_reasons.append("Missing or invalid official profile URL")

    # 5. Commercial Evidence Gate (Missing Evidence)
    if policy.commercial_evidence_required:
        if not lead.commercial_evidence_url or not is_valid_url(lead.commercial_evidence_url):
            missing_evidence_reasons.append(
                "Missing verified commercial evidence URL (must link to course, consulting, sponsors, or booking offer)"
            )

    # 6. Workflow Need Evidence Gate (Missing Evidence)
    if policy.workflow_need_evidence_required:
        if not lead.workflow_need_evidence_url or not is_valid_url(lead.workflow_need_evidence_url):
            missing_evidence_reasons.append(
                "Missing verified workflow need evidence URL (e.g. repurposing friction, backlog, multi-platform gap)"
            )

    # 7. Public Business Contact Gate (Missing Evidence)
    if policy.public_business_contact_required:
        if not (lead.business_contact_value or "").strip():
            missing_evidence_reasons.append("Missing public business contact value (email, form, or verified handle)")
        if not (lead.business_contact_type or "").strip():
            missing_evidence_reasons.append("Missing business contact channel type")
        if not lead.business_contact_source_url or not is_valid_url(lead.business_contact_source_url):
            missing_evidence_reasons.append("Missing or invalid business contact source verification URL")

    # 8. Business Contact Activity Gate (Max 60 days) (Exclusionary if verified inactive)
    if policy.public_business_contact_required:
        contact_days = calculate_days_ago(lead.business_contact_last_active, ref_dt)
        if contact_days is None:
            missing_evidence_reasons.append("Missing business contact last active date; cannot confirm active channel")
        elif contact_days > policy.contact_activity_days_max:
            exclusionary_reasons.append(
                f"Business contact last active {contact_days} days ago (exceeds {policy.contact_activity_days_max} days limit)"
            )

    # 9. Activity Gate (Exclusionary if inactive)
    content_dates_parsed = [
        calculate_days_ago(d, ref_dt) for d in lead.recent_content_dates if d
    ]
    valid_dates = [d for d in content_dates_parsed if d is not None]

    items_last_30d = sum(1 for d in valid_dates if d <= 30)
    items_last_60d = sum(1 for d in valid_dates if d <= 60)

    has_30d_activity = items_last_30d >= policy.activity_gate.content_items_last_30_days_min
    has_60d_longform = items_last_60d >= policy.activity_gate.long_form_items_last_60_days_min

    if policy.activity_gate.mode == "either":
        if not (has_30d_activity or has_60d_longform):
            exclusionary_reasons.append(
                f"Activity threshold not met: found {items_last_30d} items in last 30d (need {policy.activity_gate.content_items_last_30_days_min}) "
                f"and {items_last_60d} items in last 60d (need {policy.activity_gate.long_form_items_last_60_days_min})"
            )
    else:
        if not has_30d_activity:
            exclusionary_reasons.append(
                f"Activity in last 30d not met: found {items_last_30d} (need {policy.activity_gate.content_items_last_30_days_min})"
            )
        if not has_60d_longform:
            exclusionary_reasons.append(
                f"Long-form activity in last 60d not met: found {items_last_60d} (need {policy.activity_gate.long_form_items_last_60_days_min})"
            )

    # 10. Evidence Freshness Gate (Exclusionary if stale; missing evidence if not checked)
    evidence_days = calculate_days_ago(lead.evidence_checked_at, ref_dt)
    if evidence_days is None:
        missing_evidence_reasons.append("Missing evidence_checked_at timestamp; proof freshness unverified")
    elif evidence_days > policy.evidence_freshness_days_max:
        exclusionary_reasons.append(
            f"Evidence was checked {evidence_days} days ago (exceeds freshness window of {policy.evidence_freshness_days_max} days)"
        )

    if exclusionary_reasons:
        return QualificationStatus.DISQUALIFIED.value, exclusionary_reasons
    elif missing_evidence_reasons:
        return QualificationStatus.NEEDS_REVIEW.value, missing_evidence_reasons
    else:
        return QualificationStatus.QUALIFIED.value, []


def evaluate_hard_gates(
    lead: Lead,
    policy: QualificationPolicy,
    reference_date: Optional[datetime] = None,
) -> Tuple[bool, List[str]]:
    """
    Evaluate all non-negotiable hard gates from qualification_config.json.
    Returns (all_passed, list_of_reasons).
    """
    status, reasons = classify_candidate_gates(lead, policy, reference_date)
    passed = (status == QualificationStatus.QUALIFIED.value)
    return passed, reasons


def calculate_lead_score(
    lead: Lead,
    weights: ScoringWeights,
    reference_date: Optional[datetime] = None,
) -> float:
    """
    Compute qualification score across 5 weighted dimensions:
    1. workflow_need (max 30)
    2. segment_fit (max 25)
    3. commercial_intent (max 20)
    4. publishing_consistency (max 15)
    5. contact_channel_quality (max 10)
    Total possible: 100 points.
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    score = 0.0

    # 1. Workflow Need (max 30)
    if lead.workflow_need_evidence_url:
        score += 20.0
        # Bonus for specific known high-friction segments or multi-platform backlog
        norm_type = (lead.creator_type or "").lower()
        if "podcast" in norm_type or len(lead.recent_content_urls) >= 4:
            score += 10.0
        else:
            score += 5.0
    score = min(score, float(weights.workflow_need))

    # 2. Segment Fit (max 25)
    norm_type = (lead.creator_type or "").lower()
    segment_score = 0.0
    if norm_type in ("video_podcaster", "podcaster"):
        segment_score = 25.0
    elif norm_type == "youtube_video_first_creator":
        segment_score = 22.0
    elif norm_type in ("coach_creator", "consultant_creator", "educator_creator"):
        segment_score = 20.0
    else:
        segment_score = 10.0
    score += min(segment_score, float(weights.segment_fit))

    # 3. Commercial Intent (max 20)
    commercial_score = 0.0
    if lead.commercial_evidence_url:
        commercial_score = 20.0
    score += min(commercial_score, float(weights.commercial_intent))

    # 4. Publishing Consistency (max 15)
    valid_dates = [
        calculate_days_ago(d, ref_dt) for d in lead.recent_content_dates if d
    ]
    dates_30d = sum(1 for d in valid_dates if d is not None and d <= 30)
    dates_60d = sum(1 for d in valid_dates if d is not None and d <= 60)

    if dates_30d >= 12 or dates_60d >= 4:
        consistency_score = 15.0
    elif dates_30d >= 8 or dates_60d >= 2:
        consistency_score = 12.0
    else:
        consistency_score = 5.0
    score += min(consistency_score, float(weights.publishing_consistency))

    # 5. Contact Channel Quality (max 10)
    contact_score = 0.0
    ctype = (lead.business_contact_type or "").lower()
    if ctype in ("email", "contact_page", "form"):
        contact_score = 10.0
    elif ctype in ("social_dm", "linkedin_message", "twitter_dm"):
        contact_score = 6.0
    else:
        contact_score = 3.0
    score += min(contact_score, float(weights.contact_channel_quality))

    return round(score, 1)


def assign_priority(
    lead: Lead,
    score: float,
    reference_date: Optional[datetime] = None,
) -> Optional[str]:
    """
    Assign Priority A, B, or C:
    - Priority A: Score >= 80, specific recent content URL to reference, and contact active within 30 days.
    - Priority B: Score >= 65.
    - Priority C: Score < 65.
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    contact_days = calculate_days_ago(lead.business_contact_last_active, ref_dt) or 999

    has_recent_content_url = len(lead.recent_content_urls) > 0
    contact_very_fresh = contact_days <= 30

    if score >= 80.0 and has_recent_content_url and contact_very_fresh:
        return "A"
    elif score >= 65.0:
        return "B"
    else:
        return "C"


def qualify_lead(
    lead: Lead,
    config: AppConfig,
    reference_date: Optional[datetime] = None,
    run_id: Optional[str] = None,
) -> Tuple[Lead, VerificationLog]:
    """
    Execute end-to-end qualification against a single candidate.
    Creates structured audit log entry for transparency.
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    status_before = lead.qualification_status

    status, reasons = classify_candidate_gates(
        lead=lead,
        policy=config.qualification_policy,
        reference_date=ref_dt,
    )

    if status == QualificationStatus.QUALIFIED.value:
        lead.qualification_status = QualificationStatus.QUALIFIED.value
        lead.disqualification_reasons = []
        lead.score = calculate_lead_score(
            lead=lead,
            weights=config.scoring_after_hard_gates,
            reference_date=ref_dt,
        )
        lead.priority = assign_priority(
            lead=lead,
            score=lead.score,
            reference_date=ref_dt,
        )
    elif status == QualificationStatus.NEEDS_REVIEW.value:
        lead.qualification_status = QualificationStatus.NEEDS_REVIEW.value
        lead.disqualification_reasons = reasons
        lead.score = 0.0
        lead.priority = None
    else:
        lead.qualification_status = QualificationStatus.DISQUALIFIED.value
        lead.disqualification_reasons = reasons
        lead.score = 0.0
        lead.priority = None

    lead.last_checked_at = ref_dt.isoformat()
    if run_id:
        lead.last_run_id = run_id

    # Create verification audit record
    vlog = VerificationLog(
        lead_id=lead.id,
        platform=lead.platform,
        platform_id=lead.platform_id,
        action="qualification_evaluation",
        status_before=status_before,
        status_after=lead.qualification_status,
        disqualification_reasons=lead.disqualification_reasons,
        score=lead.score,
        priority=lead.priority,
        timestamp=ref_dt.isoformat(),
        run_id=run_id or lead.last_run_id,
        details={
            "creator_name": lead.creator_name,
            "creator_type": lead.creator_type,
            "country": lead.country,
            "commercial_evidence_url": lead.commercial_evidence_url,
            "workflow_need_evidence_url": lead.workflow_need_evidence_url,
            "passed_hard_gates": (status == QualificationStatus.QUALIFIED.value),
            "qualification_status": status,
            "is_synthetic": getattr(lead, "is_synthetic", False),
        },
    )

    return lead, vlog


def validate_country_mix(
    leads: List[Lead],
    policy: QualificationPolicy,
) -> Dict[str, Any]:
    """
    Validate target pool geography against Day 1 policy:
    - Min 80% in approved countries
    - Min 3 distinct countries represented
    - Max 60% share in any single country
    Only real qualified leads are counted.
    """
    qualified_leads = [
        l for l in leads
        if l.qualification_status == QualificationStatus.QUALIFIED.value
        and not getattr(l, "is_synthetic", False)
    ]
    total_q = len(qualified_leads)
    if total_q == 0:
        return {
            "total_qualified": 0,
            "share_allowed_countries": 0.0,
            "distinct_countries": 0,
            "max_single_country_share": 0.0,
            "meets_policy": False,
            "warnings": ["No real qualified leads in pool to validate country distribution."],
            "breakdown": {},
        }

    allowed_set = {c.strip().lower() for c in policy.allowed_countries}
    counts: Dict[str, int] = {}
    allowed_count = 0

    for l in qualified_leads:
        country_name = (l.country or "Unknown").strip()
        counts[country_name] = counts.get(country_name, 0) + 1
        if country_name.lower() in allowed_set:
            allowed_count += 1

    share_allowed = round(allowed_count / total_q, 3)
    distinct_count = len(counts)
    max_share = round(max(counts.values()) / total_q, 3) if counts else 0.0

    warnings: List[str] = []
    if share_allowed < policy.minimum_share_allowed_countries:
        warnings.append(
            f"Approved countries share ({share_allowed * 100:.1f}%) below minimum target of {policy.minimum_share_allowed_countries * 100:.0f}%"
        )
    if distinct_count < policy.minimum_distinct_countries:
        warnings.append(
            f"Distinct countries represented ({distinct_count}) below minimum requirement of {policy.minimum_distinct_countries}"
        )
    if max_share > policy.maximum_share_single_country:
        warnings.append(
            f"Single country concentration ({max_share * 100:.1f}%) exceeds maximum ceiling of {policy.maximum_share_single_country * 100:.0f}%"
        )

    return {
        "total_qualified": total_q,
        "share_allowed_countries": share_allowed,
        "distinct_countries": distinct_count,
        "max_single_country_share": max_share,
        "meets_policy": len(warnings) == 0,
        "warnings": warnings,
        "breakdown": counts,
    }
