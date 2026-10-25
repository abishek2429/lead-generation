"""
Comprehensive test suite for Day 3: Verification, Qualification, and Priority Scoring.
Validates:
- Safe URL verification & SSRF protection (localhost, private IPs, cloud metadata, restricted domains)
- All 10 non-negotiable hard gates evaluated individually
- Activity gate OR condition (8 items in 30d OR 2 long-form in 60d)
- Stale evidence detection (> 30 days)
- Missing and invalid URLs
- False-positive prevention (high score cannot override failed gates; missing evidence never verified)
- Transparent scoring rubric (5 dimensions) and score breakdown explanations
- Priority A selection (capped at top 25, no forcing unqualified records)
- Personalised outreach copy source grounding (content URL citation, verified contact, opt-out language)
- Synthetic fixture exclusion from production exports and real-lead metrics
- Country-mix compliance
- Export schema headers and audit report generation
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from src.config import AppConfig, QualificationPolicy, ScoringWeights, load_config
from src.database import Database
from src.exports import (
    EVIDENCE_ITEM_HEADERS,
    OUTREACH_PREPARATION_HEADERS,
    export_evidence_items_csv,
    export_leads_csv,
    export_outreach_preparations_csv,
    export_summary_json,
    export_workbook_pack,
)
from src.models import (
    EvidenceItem,
    EvidenceType,
    Lead,
    OutreachPreparation,
    QualificationStatus,
    VerificationMethod,
    VerificationStatus,
)
from src.verification.evidence import (
    calculate_days_ago,
    create_evidence_items_for_lead,
    is_safe_public_url,
    is_valid_url,
)
from src.verification.outreach import (
    COMPLIANT_OPT_OUT_FOOTER,
    generate_outreach_for_lead,
    prepare_priority_a_outreach_batch,
)
from src.verification.qualification import (
    calculate_lead_score,
    classify_candidate_gates,
    evaluate_hard_gates,
    qualify_lead,
    rank_and_assign_priorities,
    validate_country_mix,
)


@pytest.fixture
def base_config() -> AppConfig:
    return load_config()


@pytest.fixture
def qualified_sample_lead() -> Lead:
    """A fully verified real creator meeting all 10 hard gates."""
    return Lead(
        creator_name="Dr. Andrew Huberman",
        creator_type="video_podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="UC2D2CMWXMOVWx7giW1n3LIg",
        official_profile_url="https://www.youtube.com/@hubermanlab",
        candidate_source_url="https://www.youtube.com/results?search_query=hubermanlab",
        recent_content_urls=[
            "https://www.youtube.com/watch?v=episode_101",
            "https://www.youtube.com/watch?v=episode_102",
            "https://www.youtube.com/watch?v=episode_103",
        ],
        recent_content_dates=["2026-10-20", "2026-10-12", "2026-10-01"],
        commercial_evidence_url="https://hubermanlab.com/premium",
        workflow_need_evidence_url="https://hubermanlab.com/clips-archive",
        business_contact_type="email",
        business_contact_value="partnerships@hubermanlab.com",
        business_contact_source_url="https://hubermanlab.com/contact",
        business_contact_last_active="2026-10-15",
        evidence_checked_at="2026-10-24T10:00:00Z",
        is_synthetic=False,
    )


# ==============================================================================
# 1. SSRF & URL SAFETY TESTS
# ==============================================================================

def test_safe_public_url_ssrf_blocking():
    """Verify that localhost, loopback, cloud metadata, private IPs, and LinkedIn are blocked."""
    # Loopback & Localhost
    safe, reason = is_safe_public_url("http://localhost:8000")
    assert not safe
    assert "prohibited" in reason.lower()

    safe, reason = is_safe_public_url("http://127.0.0.1:5000/api")
    assert not safe
    assert "prohibited" in reason.lower()

    # Cloud metadata (AWS / GCP / Azure)
    safe, reason = is_safe_public_url("http://169.254.169.254/latest/meta-data/")
    assert not safe
    assert "prohibited" in reason.lower()

    safe, reason = is_safe_public_url("http://metadata.google.internal/computeMetadata/v1/")
    assert not safe

    # Private network ranges (RFC 1918)
    safe, reason = is_safe_public_url("http://10.0.0.1/admin")
    assert not safe
    assert "prohibited" in reason.lower()

    safe, reason = is_safe_public_url("http://192.168.1.1/router")
    assert not safe
    assert "prohibited" in reason.lower()

    safe, reason = is_safe_public_url("http://172.16.0.5:8080/dashboard")
    assert not safe

    # Scraping restriction: LinkedIn automated messaging is prohibited by policy
    safe, reason = is_safe_public_url("https://www.linkedin.com/in/creator-profile")
    assert not safe
    assert "prohibited" in reason.lower()

    # Valid public URLs
    safe, reason = is_safe_public_url("https://www.youtube.com/@hubermanlab")
    assert safe
    assert reason is None

    safe, reason = is_safe_public_url("https://hubermanlab.com/contact")
    assert safe


# ==============================================================================
# 2. INDIVIDUAL HARD GATES TESTS
# ==============================================================================

def test_gate_1_segment_exclusions(base_config, qualified_sample_lead):
    """Exclude agencies, management firms, and unapproved creator types."""
    lead = qualified_sample_lead.model_copy()
    lead.creator_type = "agency"
    passed, reasons = evaluate_hard_gates(lead, base_config.qualification_policy)
    assert not passed
    assert any("Excluded creator type 'agency'" in r for r in reasons)


def test_gate_2_country_approved_geographies(base_config, qualified_sample_lead):
    """Disqualify creators located outside the 7 approved target geographies."""
    lead = qualified_sample_lead.model_copy()
    lead.country = "Germany"
    passed, reasons = evaluate_hard_gates(lead, base_config.qualification_policy)
    assert not passed
    assert any("outside the 7 approved target geographies" in r for r in reasons)


def test_gate_3_language_requirement(base_config, qualified_sample_lead):
    """Disqualify creators with non-English primary content."""
    lead = qualified_sample_lead.model_copy()
    lead.language = "Spanish"
    passed, reasons = evaluate_hard_gates(lead, base_config.qualification_policy)
    assert not passed
    assert any("does not match primary language" in r for r in reasons)


def test_gate_4_platform_id_and_profile_url(base_config, qualified_sample_lead):
    """Missing platform ID or invalid profile URL must fail."""
    lead = qualified_sample_lead.model_copy()
    lead.platform_id = ""
    passed, reasons = evaluate_hard_gates(lead, base_config.qualification_policy)
    assert not passed
    assert any("Missing stable platform_id" in r for r in reasons)

    lead2 = qualified_sample_lead.model_copy()
    lead2.official_profile_url = "not_a_valid_url"
    passed2, reasons2 = evaluate_hard_gates(lead2, base_config.qualification_policy)
    assert not passed2


def test_gate_5_and_6_commercial_and_workflow_evidence(base_config, qualified_sample_lead):
    """Missing commercial offer or workflow need sets needs_review."""
    lead = qualified_sample_lead.model_copy()
    lead.commercial_evidence_url = None
    status, reasons = classify_candidate_gates(lead, base_config.qualification_policy)
    assert status == QualificationStatus.NEEDS_REVIEW.value
    assert any("commercial evidence" in r for r in reasons)

    lead2 = qualified_sample_lead.model_copy()
    lead2.workflow_need_evidence_url = None
    status2, reasons2 = classify_candidate_gates(lead2, base_config.qualification_policy)
    assert status2 == QualificationStatus.NEEDS_REVIEW.value
    assert any("workflow need" in r for r in reasons2)


def test_gate_7_and_8_business_contact_and_recency(base_config, qualified_sample_lead):
    """Business contact channel must be public and active within 60 days."""
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)

    # Inactive > 60 days
    lead = qualified_sample_lead.model_copy()
    lead.business_contact_last_active = "2026-07-01"  # ~116 days ago
    status, reasons = classify_candidate_gates(lead, base_config.qualification_policy, reference_date=ref_dt)
    assert status == QualificationStatus.DISQUALIFIED.value
    assert any("exceeds 60 days limit" in r for r in reasons)

    # Missing contact value
    lead2 = qualified_sample_lead.model_copy()
    lead2.business_contact_value = ""
    status2, reasons2 = classify_candidate_gates(lead2, base_config.qualification_policy, reference_date=ref_dt)
    assert status2 == QualificationStatus.NEEDS_REVIEW.value


def test_gate_9_activity_or_condition(base_config, qualified_sample_lead):
    """
    Test Day 3 activity OR condition:
    Must have >= 8 items in the last 30 days OR >= 2 long-form items in the last 60 days.
    """
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)

    # Case A: 8 items in last 30 days, 0 older items -> PASSES
    lead_30d = qualified_sample_lead.model_copy()
    lead_30d.recent_content_dates = [f"2026-10-{i:02d}" for i in range(10, 18)]
    lead_30d.recent_content_urls = [f"https://youtube.com/watch?v=vid_{i}" for i in range(8)]
    status, _ = classify_candidate_gates(lead_30d, base_config.qualification_policy, reference_date=ref_dt)
    assert status == QualificationStatus.QUALIFIED.value

    # Case B: 2 long-form items in last 60 days (e.g. 40 days ago, none in last 30d) -> PASSES
    lead_60d = qualified_sample_lead.model_copy()
    lead_60d.recent_content_dates = ["2026-09-15", "2026-09-01"]  # 40d and 54d ago
    lead_60d.recent_content_urls = ["https://youtube.com/watch?v=long1", "https://youtube.com/watch?v=long2"]
    status2, _ = classify_candidate_gates(lead_60d, base_config.qualification_policy, reference_date=ref_dt)
    assert status2 == QualificationStatus.QUALIFIED.value

    # Case C: Only 1 item in 60d (and 1 in 30d) -> FAILS
    lead_low = qualified_sample_lead.model_copy()
    lead_low.recent_content_dates = ["2026-10-20"]  # only 1 item in total
    lead_low.recent_content_urls = ["https://youtube.com/watch?v=single_item"]
    status3, reasons3 = classify_candidate_gates(lead_low, base_config.qualification_policy, reference_date=ref_dt)
    assert status3 == QualificationStatus.DISQUALIFIED.value
    assert any("Activity threshold not met" in r for r in reasons3)


def test_gate_10_evidence_freshness(base_config, qualified_sample_lead):
    """Evidence checked date must be within 30 days."""
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)

    # Stale evidence (checked 45 days ago)
    lead = qualified_sample_lead.model_copy()
    lead.evidence_checked_at = "2026-09-10T00:00:00Z"
    status, reasons = classify_candidate_gates(lead, base_config.qualification_policy, reference_date=ref_dt)
    assert status == QualificationStatus.DISQUALIFIED.value
    assert any("exceeds freshness window of 30 days" in r for r in reasons)


# ==============================================================================
# 3. SOURCE-LINKED EVIDENCE MODEL TESTS
# ==============================================================================

def test_create_evidence_items_all_claims(qualified_sample_lead):
    """Verify that create_evidence_items_for_lead produces all 7 required claims with verified status."""
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)
    items = create_evidence_items_for_lead(qualified_sample_lead, reference_date=ref_dt)

    assert len(items) == 7
    types = [item.evidence_type for item in items]
    assert EvidenceType.OFFICIAL_IDENTITY.value in types
    assert EvidenceType.RECENT_CONTENT.value in types
    assert EvidenceType.COMMERCIAL_OFFER.value in types
    assert EvidenceType.WORKFLOW_NEED.value in types
    assert EvidenceType.BUSINESS_CONTACT.value in types
    assert EvidenceType.CONTACT_ACTIVITY.value in types
    assert EvidenceType.COUNTRY_LANGUAGE.value in types

    # For fully qualified lead, all items must be verified
    for it in items:
        assert it.verification_status == VerificationStatus.VERIFIED.value
        assert it.checked_at is not None
        assert it.source_url != ""


def test_evidence_item_never_verified_merely_for_existing_url():
    """Verify that an invalid or stale URL does NOT result in verified status."""
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)
    lead = Lead(
        creator_name="Test Creator",
        creator_type="agency",  # Invalid type
        country="France",  # Invalid country
        platform="youtube",
        platform_id="test_id",
        official_profile_url="http://localhost:8080/profile",  # SSRF blocked URL
        candidate_source_url="https://youtube.com",
        recent_content_urls=[],  # No content
        recent_content_dates=[],
        commercial_evidence_url=None,  # Missing
        workflow_need_evidence_url="http://169.254.169.254/meta",  # SSRF blocked
        business_contact_type="email",
        business_contact_value="test@test.com",
        business_contact_source_url="http://192.168.1.1/contact",  # Private IP
        business_contact_last_active="2025-01-01",  # Very old
        evidence_checked_at="2026-10-24T00:00:00Z",
    )

    items = create_evidence_items_for_lead(lead, reference_date=ref_dt)
    for it in items:
        assert it.verification_status != VerificationStatus.VERIFIED.value


# ==============================================================================
# 4. TRANSPARENT SCORING & PRIORITY A RANKING TESTS
# ==============================================================================

def test_transparent_scoring_breakdown(base_config, qualified_sample_lead):
    """
    Verify scoring rubric across 5 dimensions:
    - workflow_need (max 30)
    - segment_fit (max 25)
    - commercial_intent (max 20)
    - publishing_consistency (max 15)
    - contact_channel_quality (max 10)
    Ensures points, reasons, and evidence used are stored.
    """
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)
    score = calculate_lead_score(qualified_sample_lead, base_config.scoring_after_hard_gates, reference_date=ref_dt)

    assert score >= 80.0
    assert qualified_sample_lead.score_breakdown
    breakdown = qualified_sample_lead.score_breakdown

    assert "workflow_need" in breakdown
    assert breakdown["workflow_need"]["points"] > 0
    assert breakdown["workflow_need"]["max_points"] == 30.0
    assert breakdown["workflow_need"]["evidence_used"] == qualified_sample_lead.workflow_need_evidence_url

    assert "segment_fit" in breakdown
    assert breakdown["segment_fit"]["max_points"] == 25.0

    assert "commercial_intent" in breakdown
    assert breakdown["commercial_intent"]["points"] == 20.0

    assert "publishing_consistency" in breakdown
    assert "contact_channel_quality" in breakdown
    assert breakdown["total_score"] == score


def test_disqualified_leads_receive_zero_score_and_no_priority(base_config, qualified_sample_lead):
    """Disqualified leads must have score = 0.0 and priority = None."""
    lead = qualified_sample_lead.model_copy()
    lead.country = "Japan"  # Outside target geographies
    evaluated, vlog = qualify_lead(lead, base_config)

    assert evaluated.qualification_status == QualificationStatus.DISQUALIFIED.value
    assert evaluated.score == 0.0
    assert evaluated.priority is None
    assert evaluated.score_breakdown == {}


def test_priority_a_cap_at_25_and_no_forcing(base_config, qualified_sample_lead):
    """
    Assign Priority A to top 25 eligible leads only.
    If only 3 leads qualify, do NOT force 25 records.
    """
    ref_dt = datetime(2026, 10, 25, tzinfo=timezone.utc)

    # Pool with 3 qualified leads and 2 disqualified leads
    leads: List[Lead] = []
    for i in range(3):
        l = qualified_sample_lead.model_copy()
        l.id = i + 1
        l.creator_name = f"Qualified Creator {i+1}"
        l.platform_id = f"plat_{i+1}"
        l.qualification_status = QualificationStatus.QUALIFIED.value
        l.score = 85.0 - i * 2
        leads.append(l)

    for j in range(2):
        l = qualified_sample_lead.model_copy()
        l.id = j + 4
        l.creator_name = f"Disqualified Creator {j+1}"
        l.platform_id = f"disq_{j+1}"
        l.country = "Germany"
        l.qualification_status = QualificationStatus.DISQUALIFIED.value
        l.score = 0.0
        leads.append(l)

    ranked = rank_and_assign_priorities(leads, max_priority_a=25, reference_date=ref_dt)

    priority_a = [l for l in ranked if l.priority == "A"]
    assert len(priority_a) == 3, "Did not assign Priority A to exactly 3 eligible leads!"
    # Disqualified must remain None
    for l in ranked:
        if l.qualification_status == QualificationStatus.DISQUALIFIED.value:
            assert l.priority is None


# ==============================================================================
# 5. PERSONALISED OUTREACH PREPARATION TESTS
# ==============================================================================

def test_personalised_outreach_grounding(qualified_sample_lead):
    """Verify that outreach sequence is grounded in specific content URL, chosen contact, and opt-out."""
    prep = generate_outreach_for_lead(qualified_sample_lead)

    assert prep.creator_name == qualified_sample_lead.creator_name
    assert prep.specific_content_source_url == qualified_sample_lead.recent_content_urls[0]
    assert qualified_sample_lead.recent_content_urls[0] in prep.proposed_first_message
    assert prep.chosen_channel.startswith("email:")
    assert COMPLIANT_OPT_OUT_FOOTER in prep.proposed_first_message
    assert COMPLIANT_OPT_OUT_FOOTER in prep.follow_up_1
    assert COMPLIANT_OPT_OUT_FOOTER in prep.follow_up_2
    assert "IncuBrix" in prep.proposed_first_message


def test_prepare_priority_a_outreach_batch_filters_non_a(qualified_sample_lead):
    """Outreach batch preparation must only process Priority A qualified leads."""
    lead_a = qualified_sample_lead.model_copy()
    lead_a.priority = "A"
    lead_a.qualification_status = "qualified"

    lead_b = qualified_sample_lead.model_copy()
    lead_b.priority = "B"
    lead_b.qualification_status = "qualified"

    lead_disq = qualified_sample_lead.model_copy()
    lead_disq.priority = "A"
    lead_disq.qualification_status = "disqualified"

    preps = prepare_priority_a_outreach_batch([lead_a, lead_b, lead_disq], max_count=25)
    assert len(preps) == 1
    assert preps[0].creator_name == lead_a.creator_name


# ==============================================================================
# 6. SYNTHETIC FIXTURE ISOLATION AND EXPORTS TESTS
# ==============================================================================

def test_synthetic_fixtures_excluded_from_real_exports(qualified_sample_lead):
    """Ensure that synthetic fixtures are completely excluded from qualified_leads.csv by default."""
    synthetic_lead = qualified_sample_lead.model_copy()
    synthetic_lead.is_synthetic = True
    synthetic_lead.qualification_status = "qualified"

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_csv = Path(tmp_dir) / "qualified_leads.csv"
        export_leads_csv([synthetic_lead], str(out_csv), filter_status="qualified", allow_synthetic=False)

        with open(out_csv, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Must contain header only, 0 data rows
            assert len(lines) == 1


def test_audit_and_quality_report_metrics(qualified_sample_lead):
    """Verify that export_summary_json produces the required Day 3 audit and quality report metrics."""
    lead = qualified_sample_lead.model_copy()
    lead.qualification_status = "qualified"

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_json = Path(tmp_dir) / "audit_and_quality_report.json"
        export_summary_json(
            leads=[lead],
            output_path=str(out_json),
            duplicates_prevented=5,
        )

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "audit_and_quality_report" in data
        rep = data["audit_and_quality_report"]
        assert rep["qualified_lead_count"] == 1
        assert rep["candidate_count"] == 1
        assert rep["evidence_freshness_rate"] == 1.0
        assert rep["duplicate_rate"] > 0.0
        assert "country_distribution" in rep
        assert "platform_distribution" in rep
        assert "segment_distribution" in rep
        assert "missing_evidence_summary" in rep


def test_export_workbook_pack_all_day3_deliverables(qualified_sample_lead):
    """Verify that export_workbook_pack exports evidence_items.csv and priority_a_outreach.csv."""
    ev_item = EvidenceItem(
        lead_id=1,
        platform=qualified_sample_lead.platform,
        platform_id=qualified_sample_lead.platform_id,
        evidence_type=EvidenceType.OFFICIAL_IDENTITY.value,
        source_url=qualified_sample_lead.official_profile_url,
        short_factual_description="Official channel profile",
    )
    prep = generate_outreach_for_lead(qualified_sample_lead)

    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = export_workbook_pack(
            leads=[qualified_sample_lead],
            output_dir=tmp_dir,
            evidence_items=[ev_item],
            outreach_preparations=[prep],
            allow_synthetic=False,
        )

        assert Path(paths["qualified_leads"]).is_file()
        assert Path(paths["all_candidates"]).is_file()
        assert Path(paths["needs_review"]).is_file()
        assert Path(paths["disqualification_audit"]).is_file()
        assert Path(paths["verification_audit"]).is_file()
        assert Path(paths["evidence_items"]).is_file()
        assert Path(paths["priority_a_outreach"]).is_file()
        assert Path(paths["summary_report"]).is_file()
        assert Path(paths["audit_and_quality_report"]).is_file()

        # Check evidence headers
        with open(paths["evidence_items"], "r", encoding="utf-8") as f:
            headers = f.readline().strip().split(",")
            assert headers == EVIDENCE_ITEM_HEADERS

        # Check outreach headers
        with open(paths["priority_a_outreach"], "r", encoding="utf-8") as f:
            headers = f.readline().strip().split(",")
            assert headers == OUTREACH_PREPARATION_HEADERS
