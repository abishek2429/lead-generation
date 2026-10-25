"""
Comprehensive test suite for Day 4: Multi-Channel Outreach Engine.

Verifies:
1. Deterministic channel selection (Email, LinkedIn, Instagram) and explicit DB reasons.
2. Channel recency cutoff (<= 60 days) and fallback to 'needs_review'.
3. 15-template matrix (5 segments x 3 channels x 3 touches = 45 touches).
4. Honest sender identity: "IncuBrix Growth Engineer Assessment Candidate".
5. Message personalisation grounded in verified recent content URLs.
6. Missing evidence suppression (never generating fake claims).
7. Three distinct touches with delays (+0, +3, +7 days).
8. Compliant opt-out footer enforcement.
9. Safe seed testing authorization check (blocks unauthorized real creator endpoints).
10. Tracking-link generation, open/click/reply event logging, and state transitions.
11. Opt-out suppression list blocking subsequent delivery.
12. CRM export schema validation and synthetic test fixture isolation.
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.models import (
    Lead,
    EvidenceItem,
    OutreachPreparation,
    OutreachTemplate,
    DeliveryEvent,
    SuppressionRecord,
    current_utc_iso,
)
from src.database import Database
from src.verification.channels import (
    select_channels_for_lead,
    normalize_segment,
    extract_available_channels,
    ChannelSelectionResult,
)
from src.verification.templates import (
    get_all_templates,
    render_touch,
    validate_lead_personalisation_evidence,
    SENDER_IDENTITY,
    EMAIL_OPT_OUT,
)
from src.verification.outreach import (
    generate_outreach_for_lead,
    prepare_all_qualified_outreach,
    prepare_priority_a_outreach_batch,
)
from src.verification.seed_testing import (
    SeedSimulator,
    UnauthorizedEndpointError,
    is_authorized_test_endpoint,
    generate_tracking_link,
)
from src.exports import (
    DAY4_OUTREACH_HEADERS,
    OUTREACH_TEMPLATE_HEADERS,
    export_outreach_priority_a_csv,
    export_outreach_all_qualified_csv,
    export_outreach_templates_csv,
)


@pytest.fixture
def test_db(tmp_path):
    """Isolated temporary SQLite database for testing."""
    db_file = tmp_path / "test_outreach.db"
    return Database(str(db_file))


@pytest.fixture
def qualified_podcaster_lead():
    """Sample verified podcaster lead with recent content and business email."""
    now = datetime.now(timezone.utc)
    return Lead(
        id=101,
        creator_name="Lex Fridman",
        creator_type="video_podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="lexfridman",
        official_profile_url="https://youtube.com/@lexfridman",
        candidate_source_url="https://youtube.com/@lexfridman",
        recent_content_urls=["https://youtube.com/watch?v=lex_recent_400"],
        recent_content_dates=[(now - timedelta(days=3)).strftime("%Y-%m-%d")],
        commercial_evidence_url="https://lexfridman.com/sponsors",
        workflow_need_evidence_url="https://youtube.com/@lexfridman/shorts",
        business_contact_type="email",
        business_contact_value="business@lexfridman.com",
        business_contact_source_url="https://lexfridman.com/contact",
        business_contact_last_active=(now - timedelta(days=5)).strftime("%Y-%m-%d"),
        evidence_checked_at=now.isoformat(),
        qualification_status="qualified",
        score=88.0,
        priority="A",
        is_synthetic=False,
    )


@pytest.fixture
def qualified_consultant_lead():
    """Sample B2B consultant lead with LinkedIn profile and booking email."""
    now = datetime.now(timezone.utc)
    return Lead(
        id=102,
        creator_name="Sarah Tavel",
        creator_type="consultant",
        country="United States",
        language="English",
        platform="linkedin",
        platform_id="sarahtavel",
        official_profile_url="https://linkedin.com/in/sarahtavel",
        candidate_source_url="https://linkedin.com/in/sarahtavel",
        recent_content_urls=["https://linkedin.com/posts/sarahtavel_recent_essay"],
        recent_content_dates=[(now - timedelta(days=4)).strftime("%Y-%m-%d")],
        commercial_evidence_url="https://benchmark.com/team/sarah",
        workflow_need_evidence_url="https://linkedin.com/in/sarahtavel",
        business_contact_type="email",
        business_contact_value="sarah@benchmark.com",
        business_contact_source_url="https://benchmark.com/contact",
        business_contact_last_active=(now - timedelta(days=10)).strftime("%Y-%m-%d"),
        evidence_checked_at=now.isoformat(),
        qualification_status="qualified",
        score=85.0,
        priority="A",
        is_synthetic=False,
    )


# ==============================================================================
# 1. CHANNEL SELECTION TESTS
# ==============================================================================
def test_deterministic_channel_selection_podcaster_email_primary(qualified_podcaster_lead):
    """Podcasters prefer email for production & guest booking inquiries."""
    res = select_channels_for_lead(qualified_podcaster_lead)
    assert res.primary_channel == "email"
    assert res.primary_contact_value == "business@lexfridman.com"
    assert "email" in res.primary_channel_reason.lower()
    assert res.channel_suitability_status == "suitable"


def test_deterministic_channel_selection_consultant_linkedin_backup_or_primary(qualified_consultant_lead):
    """Consultant with verified LinkedIn profile and domain email."""
    res = select_channels_for_lead(qualified_consultant_lead)
    assert res.channel_suitability_status == "suitable"
    assert res.primary_channel in ("email", "linkedin")
    assert res.backup_channel in ("linkedin", "email")
    assert len(res.primary_channel_reason) > 20
    assert len(res.backup_channel_reason) > 20


def test_channel_selection_fallback_to_needs_review_when_unverified():
    """If no verified contact route exists, channel status must be 'needs_review'."""
    unverified_lead = Lead(
        id=103,
        creator_name="Anonymous Creator",
        creator_type="youtube_creator",
        platform="youtube",
        platform_id="anon_creator",
        official_profile_url="https://youtube.com/@anon",
        candidate_source_url="https://youtube.com/@anon",
        business_contact_type=None,
        business_contact_value=None,
        qualification_status="qualified",
    )
    res = select_channels_for_lead(unverified_lead)
    assert res.channel_suitability_status == "needs_review"
    assert res.primary_channel == "needs_review"
    assert "No verified public contact channel" in res.primary_channel_reason


def test_channel_selection_respects_60_day_recency_cutoff(qualified_podcaster_lead):
    """Contacts not verified within 60 days must be treated as stale."""
    stale_lead = qualified_podcaster_lead.model_copy()
    old_date = (datetime.now(timezone.utc) - timedelta(days=75)).strftime("%Y-%m-%d")
    stale_lead.business_contact_last_active = old_date
    stale_lead.business_contact_verified_date = old_date
    stale_lead.evidence_checked_at = old_date

    res = select_channels_for_lead(stale_lead)
    assert res.channel_suitability_status == "needs_review"


# ==============================================================================
# 2. TEMPLATE CATALOGUE TESTS (5 Segments x 3 Channels x 3 Touches)
# ==============================================================================
def test_all_15_segment_channel_template_combinations_exist():
    """Must have exactly 45 structured template records (5 segments x 3 channels x 3 touches)."""
    templates = get_all_templates()
    assert len(templates) == 45

    segments = {"podcaster", "youtube_creator", "coach", "consultant", "educator"}
    channels = {"email", "linkedin", "instagram"}

    for seg in segments:
        for ch in channels:
            for touch_num in (1, 2, 3):
                t = next(
                    (t for t in templates if t.segment == seg and t.channel == ch and t.touch_number == touch_num),
                    None,
                )
                assert t is not None, f"Missing template for {seg} x {ch} x touch {touch_num}"
                assert t.suggested_delay_days in (0, 3, 7)


def test_honest_sender_identity_enforced_in_all_templates():
    """All templates must honestly identify the sender as an assessment candidate."""
    templates = get_all_templates()
    for t in templates:
        assert t.sender_identity == SENDER_IDENTITY
        assert "IncuBrix Growth Engineer Assessment Candidate" in t.sender_identity


# ==============================================================================
# 3. MESSAGE PERSONALISATION & GROUNDING TESTS
# ==============================================================================
def test_message_personalisation_cites_verified_recent_content(qualified_podcaster_lead):
    """First message must reference specific recent content URL and creator name."""
    prep = generate_outreach_for_lead(qualified_podcaster_lead)
    assert prep.validation_status == "valid"
    assert "https://youtube.com/watch?v=lex_recent_400" in prep.proposed_first_message
    assert "Lex Fridman" in prep.proposed_first_message
    assert prep.sender_identity == "IncuBrix Growth Engineer Assessment Candidate"
    assert prep.follow_up_1_delay_days == 3
    assert prep.follow_up_2_delay_days == 7
    assert len(prep.follow_up_1) > 40
    assert len(prep.follow_up_2) > 40


def test_missing_content_evidence_suppresses_personalisation():
    """If evidence is missing, do not generate fake copy; flag as 'needs_review'."""
    missing_evidence_lead = Lead(
        id=104,
        creator_name="Empty Lead",
        creator_type="educator",
        platform="youtube",
        platform_id="empty_lead",
        official_profile_url="",
        candidate_source_url="",
        recent_content_urls=[],
        business_contact_type="email",
        business_contact_value="test@empty.com",
        qualification_status="qualified",
    )
    prep = generate_outreach_for_lead(missing_evidence_lead)
    assert prep.validation_status == "needs_review"
    assert "PERSONALISATION SUPPRESSED" in prep.proposed_first_message or "Review Needed" in prep.subject_line


def test_compliant_opt_out_language_present_on_all_channels(qualified_podcaster_lead):
    """Opt-out language must be present on outreach preparations."""
    prep = generate_outreach_for_lead(qualified_podcaster_lead)
    assert "opt-out" in prep.opt_out_language.lower() or "reply 'stop'" in prep.opt_out_language.lower()


# ==============================================================================
# 4. SAFE SEED TESTING & LIFECYCLE STATE MACHINE TESTS
# ==============================================================================
def test_safe_seed_testing_blocks_unauthorized_endpoints(qualified_podcaster_lead, test_db):
    """Attempting delivery simulation to unauthorized real creator contact must raise error."""
    prep = generate_outreach_for_lead(qualified_podcaster_lead)
    # prep.primary_contact_value is 'business@lexfridman.com' (unauthorized real contact)
    with pytest.raises(UnauthorizedEndpointError):
        SeedSimulator.simulate_send(
            lead=qualified_podcaster_lead,
            prep=prep,
            touch_number=1,
            forced_test_recipient="real.creator@hubermanlab.com",
        )


def test_safe_seed_testing_delivery_and_tracking_simulation(qualified_podcaster_lead, test_db):
    """Simulate send and interaction against authorized test endpoint."""
    test_db.save_outreach_preparations([generate_outreach_for_lead(qualified_podcaster_lead)])
    prep = test_db.get_outreach_preparation_by_platform_id(qualified_podcaster_lead.platform_id)

    # 1. Send simulation to candidate-controlled endpoint
    event_sent = SeedSimulator.simulate_send(
        lead=qualified_podcaster_lead,
        prep=prep,
        touch_number=1,
        forced_test_recipient="growth.engineer.candidate@gmail.com",
        db=test_db,
    )
    assert event_sent.status == "SUCCESS"
    assert event_sent.event_type == "SENT"
    assert event_sent.tracking_token != ""

    # Check updated status
    updated_prep = test_db.get_outreach_preparation_by_platform_id(qualified_podcaster_lead.platform_id)
    assert updated_prep.outreach_status == "TOUCH_1_SENT"

    # 2. Open interaction
    open_ev = SeedSimulator.simulate_interaction(event_sent.tracking_token, "OPENED", db=test_db)
    assert open_ev.event_type == "OPENED"
    updated_prep2 = test_db.get_outreach_preparation_by_platform_id(qualified_podcaster_lead.platform_id)
    assert updated_prep2.outreach_status == "OPENED"

    # 3. Reply interaction halts automated follow-ups
    reply_ev = SeedSimulator.simulate_interaction(
        event_sent.tracking_token,
        "REPLIED",
        reply_text="Sounds interesting, please send a demo.",
        db=test_db,
    )
    assert reply_ev.event_type == "REPLIED"
    updated_prep3 = test_db.get_outreach_preparation_by_platform_id(qualified_podcaster_lead.platform_id)
    assert updated_prep3.outreach_status == "REPLIED"


def test_safe_seed_testing_opt_out_suppression(qualified_podcaster_lead, test_db):
    """Opt-out suppression must block subsequent send simulations to that contact."""
    test_db.save_outreach_preparations([generate_outreach_for_lead(qualified_podcaster_lead)])
    prep = test_db.get_outreach_preparation_by_platform_id(qualified_podcaster_lead.platform_id)
    test_email = "candidate@incubrix.local"

    # Process opt-out
    SeedSimulator.handle_opt_out(
        contact_value=test_email,
        channel="email",
        reason="Creator replied stop",
        lead_id=qualified_podcaster_lead.platform_id,
        db=test_db,
    )

    # Check suppression table
    assert test_db.is_contact_suppressed(test_email, "email") is True

    # Attempting to send again must be blocked and logged as SUPPRESSED
    blocked_event = SeedSimulator.simulate_send(
        lead=qualified_podcaster_lead,
        prep=prep,
        touch_number=2,
        forced_test_recipient=test_email,
        db=test_db,
    )

    assert blocked_event.status == "SUPPRESSED"
    assert blocked_event.event_type == "BLOCKED"


# ==============================================================================
# 5. CRM EXPORTS & SYNTHETIC DATA ISOLATION TESTS
# ==============================================================================
def test_crm_exports_correctness_and_synthetic_isolation(qualified_podcaster_lead, tmp_path):
    """Validate export schemas and verify synthetic leads are excluded in production mode."""
    real_prep = generate_outreach_for_lead(qualified_podcaster_lead)
    real_prep.is_synthetic = False

    synthetic_lead = qualified_podcaster_lead.model_copy()
    synthetic_lead.id = 999
    synthetic_lead.platform_id = "synthetic_fixture_1"
    synthetic_lead.is_synthetic = True
    synthetic_prep = generate_outreach_for_lead(synthetic_lead)
    synthetic_prep.is_synthetic = True

    preps = [real_prep, synthetic_prep]

    p_a_path = tmp_path / "outreach_priority_a.csv"
    all_q_path = tmp_path / "outreach_all_qualified.csv"
    tmpls_path = tmp_path / "outreach_templates.csv"

    # Export with allow_synthetic=False (production mode)
    export_outreach_priority_a_csv(preps, str(p_a_path), allow_synthetic=False)
    export_outreach_all_qualified_csv(preps, str(all_q_path), allow_synthetic=False)
    export_outreach_templates_csv(None, str(tmpls_path))

    import csv
    with open(p_a_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = list(reader)
        assert headers == DAY4_OUTREACH_HEADERS
        assert len(rows) == 1, "Synthetic lead was not excluded from Priority A export!"
        assert rows[0][0] == str(qualified_podcaster_lead.id)

    with open(all_q_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = list(reader)
        assert headers == DAY4_OUTREACH_HEADERS
        assert len(rows) == 1, "Synthetic lead was not excluded from All Qualified export!"

    with open(tmpls_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = list(reader)
        assert headers == OUTREACH_TEMPLATE_HEADERS
        assert len(rows) == 45, "Template catalogue must contain exactly 45 touches!"
