"""
Unit tests for Day 1 qualification policy, hard gates, scoring, and country mix validation.
"""

from datetime import datetime, timezone
import pytest
from src.config import AppConfig, QualificationPolicy, ScoringWeights
from src.models import Lead, QualificationStatus
from src.verification.qualification import (
    assign_priority,
    calculate_lead_score,
    classify_candidate_gates,
    evaluate_hard_gates,
    qualify_lead,
    validate_country_mix,
)

# Fixed reference date for deterministic testing: 2026-10-25 12:00:00 UTC
REF_DATE = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def base_policy():
    return QualificationPolicy()


@pytest.fixture
def valid_lead():
    """A lead that satisfies all Day 1 hard gates."""
    return Lead(
        creator_name="Dr. Jane Smith",
        creator_type="video_podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="UC_DR_JANE",
        official_profile_url="https://youtube.com/@drjanesmith",
        candidate_source_url="https://source.com",
        recent_content_urls=[
            "https://youtube.com/watch?v=vid1",
            "https://youtube.com/watch?v=vid2",
        ],
        recent_content_dates=[
            "2026-10-20",  # 5 days ago
            "2026-10-10",  # 15 days ago
            "2026-09-25",  # 30 days ago
        ],
        commercial_evidence_url="https://drjanesmith.com/coaching-program",
        workflow_need_evidence_url="https://drjanesmith.com/podcast-archive",
        business_contact_type="email",
        business_contact_value="booking@drjanesmith.com",
        business_contact_source_url="https://drjanesmith.com/contact",
        business_contact_last_active="2026-10-15",  # 10 days ago
        evidence_checked_at="2026-10-24T10:00:00Z",  # 1 day ago
    )


def test_valid_lead_passes_all_hard_gates(valid_lead, base_policy):
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is True
    assert reasons == []


def test_segment_gate_rejections(valid_lead, base_policy):
    # Excluded agency
    valid_lead.creator_type = "agency"
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Excluded creator type" in r for r in reasons)

    # Unknown segment
    valid_lead.creator_type = "random_blogger"
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("not in allowed target segments" in r for r in reasons)


def test_country_gate_rejections(valid_lead, base_policy):
    # Outside allowed countries
    valid_lead.country = "Germany"
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("outside the 7 approved target geographies" in r for r in reasons)

    # Missing country
    valid_lead.country = None
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Missing country" in r for r in reasons)


def test_language_gate_rejections(valid_lead, base_policy):
    valid_lead.language = "Spanish"
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("does not match primary language" in r for r in reasons)


def test_evidence_gate_rejections(valid_lead, base_policy):
    # Missing commercial evidence
    valid_lead.commercial_evidence_url = None
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Missing verified commercial evidence" in r for r in reasons)

    # Missing workflow evidence
    valid_lead.commercial_evidence_url = "https://offer.com"
    valid_lead.workflow_need_evidence_url = None
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Missing verified workflow need evidence" in r for r in reasons)


def test_business_contact_gate_rejections(valid_lead, base_policy):
    # Missing contact value
    valid_lead.business_contact_value = None
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Missing public business contact value" in r for r in reasons)

    # Contact inactive for > 60 days
    valid_lead.business_contact_value = "hello@example.com"
    valid_lead.business_contact_last_active = "2026-07-01"  # > 110 days ago
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("exceeds 60 days limit" in r for r in reasons)


def test_activity_gate_rejections(valid_lead, base_policy):
    # Mode is "either": 8 in 30d OR 2 in 60d
    # If creator only posted 1 item in 60 days:
    valid_lead.recent_content_dates = ["2026-10-20"]
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("Activity threshold not met" in r for r in reasons)

    # But 2 items in 60 days should pass
    valid_lead.recent_content_dates = ["2026-10-20", "2026-09-10"]
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is True


def test_evidence_freshness_gate_rejections(valid_lead, base_policy):
    # Older than 30 days
    valid_lead.evidence_checked_at = "2026-08-01T00:00:00Z"
    passed, reasons = evaluate_hard_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert passed is False
    assert any("exceeds freshness window" in r for r in reasons)


def test_full_qualify_lead_flow(valid_lead):
    cfg = AppConfig()
    qualified, vlog = qualify_lead(valid_lead, cfg, reference_date=REF_DATE, run_id="run_test_qual")

    assert qualified.qualification_status == QualificationStatus.QUALIFIED.value
    assert qualified.score >= 80.0
    assert qualified.priority == "A"
    assert qualified.disqualification_reasons == []
    assert vlog.status_after == "qualified"
    assert vlog.run_id == "run_test_qual"


def test_country_mix_validation(base_policy):
    leads = [
        Lead(
            creator_name=f"Creator {i}",
            creator_type="podcaster",
            country="United States",
            platform="youtube",
            platform_id=f"UC_{i}",
            official_profile_url=f"https://youtube.com/@c{i}",
            candidate_source_url="https://source.com",
            qualification_status="qualified",
        )
        for i in range(10)
    ]

    # Pool with only 1 country fails min 3 distinct countries and max 60% concentration
    res = validate_country_mix(leads, base_policy)
    assert res["meets_policy"] is False
    assert len(res["warnings"]) >= 2

    # Balanced pool
    balanced_leads = [
        Lead(creator_name="C1", creator_type="podcaster", country="United States", platform="youtube", platform_id="1", official_profile_url="u1", candidate_source_url="s", qualification_status="qualified"),
        Lead(creator_name="C2", creator_type="podcaster", country="United States", platform="youtube", platform_id="2", official_profile_url="u2", candidate_source_url="s", qualification_status="qualified"),
        Lead(creator_name="C3", creator_type="podcaster", country="United Kingdom", platform="youtube", platform_id="3", official_profile_url="u3", candidate_source_url="s", qualification_status="qualified"),
        Lead(creator_name="C4", creator_type="podcaster", country="Canada", platform="youtube", platform_id="4", official_profile_url="u4", candidate_source_url="s", qualification_status="qualified"),
        Lead(creator_name="C5", creator_type="podcaster", country="Australia", platform="youtube", platform_id="5", official_profile_url="u5", candidate_source_url="s", qualification_status="qualified"),
    ]
    balanced_res = validate_country_mix(balanced_leads, base_policy)
    assert balanced_res["meets_policy"] is True
    assert balanced_res["share_allowed_countries"] == 1.0
    assert balanced_res["distinct_countries"] == 4
    assert balanced_res["max_single_country_share"] == 0.4


def test_needs_review_classification_when_evidence_unverified(valid_lead, base_policy):
    """
    Candidates who match segment, country, and activity but lack verified evidence
    must be classified as 'needs_review' rather than 'qualified' or 'disqualified'.
    """
    # Candidate lacks commercial offer URL and workflow need URL
    valid_lead.commercial_evidence_url = None
    valid_lead.workflow_need_evidence_url = None

    status, reasons = classify_candidate_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert status == QualificationStatus.NEEDS_REVIEW.value
    assert any("commercial evidence" in r.lower() for r in reasons)
    assert any("workflow need" in r.lower() for r in reasons)


def test_missing_evidence_never_defaults_to_verified(valid_lead, base_policy):
    """Ensure missing or empty evidence fields strictly prevent qualification."""
    # 1. Missing contact value
    valid_lead.business_contact_value = ""
    status, reasons = classify_candidate_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert status == QualificationStatus.NEEDS_REVIEW.value
    assert any("contact value" in r.lower() for r in reasons)

    # 2. Stale evidence checked date (> 30 days)
    valid_lead.business_contact_value = "contact@example.com"
    valid_lead.evidence_checked_at = "2026-08-01T00:00:00Z"  # ~85 days ago
    status, reasons = classify_candidate_gates(valid_lead, base_policy, reference_date=REF_DATE)
    assert status == QualificationStatus.DISQUALIFIED.value
    assert any("freshness window" in r.lower() or "exceeds" in r.lower() for r in reasons)


def test_country_mix_filters_to_real_qualified_only(base_policy):
    """
    Ensure validate_country_mix ignores disqualified, needs_review, and synthetic leads
    when computing the real production country mix.
    """
    mixed_leads = [
        # Real qualified leads
        Lead(creator_name="R1", creator_type="podcaster", country="United States", platform="youtube", platform_id="1", official_profile_url="u1", candidate_source_url="s", qualification_status="qualified", is_synthetic=False),
        Lead(creator_name="R2", creator_type="podcaster", country="United Kingdom", platform="youtube", platform_id="2", official_profile_url="u2", candidate_source_url="s", qualification_status="qualified", is_synthetic=False),
        Lead(creator_name="R3", creator_type="podcaster", country="Canada", platform="youtube", platform_id="3", official_profile_url="u3", candidate_source_url="s", qualification_status="qualified", is_synthetic=False),
        # Synthetic fixture in Australia (should be ignored for real qualified mix)
        Lead(creator_name="Syn1", creator_type="podcaster", country="Australia", platform="youtube", platform_id="4", official_profile_url="u4", candidate_source_url="s", qualification_status="qualified", is_synthetic=True),
        # Disqualified in Germany
        Lead(creator_name="DQ1", creator_type="agency", country="Germany", platform="youtube", platform_id="5", official_profile_url="u5", candidate_source_url="s", qualification_status="disqualified", is_synthetic=False),
        # Needs review in Ireland
        Lead(creator_name="NR1", creator_type="podcaster", country="Ireland", platform="youtube", platform_id="6", official_profile_url="u6", candidate_source_url="s", qualification_status="needs_review", is_synthetic=False),
    ]

    res = validate_country_mix(mixed_leads, base_policy)
    # Only R1, R2, R3 (US, UK, Canada) count!
    assert res["total_qualified"] == 3
    assert res["distinct_countries"] == 3
    assert "Germany" not in res["breakdown"]
    assert "Australia" not in res["breakdown"]
    assert res["meets_policy"] is True

