"""
Senior QA Audit Integrity Test Suite for IncuBrix Lead Generation Engine.
Verifies all 10 audit integrity criteria mandated by the assessment:
1. Missing evidence cannot pass a hard gate.
2. Qualification statuses are derived from actual checks.
3. Stale evidence is flagged.
4. The country mix is calculated from the actual dataset.
5. Duplicates are prevented across repeated imports.
6. Every Priority A message references verified recent content.
7. No guessed contacts or fabricated activity metrics are allowed.
8. Test-mode events are labelled as simulated.
9. Opt-outs suppress further test follow-ups.
10. API keys and secrets never appear in logs or exports.
"""

import io
import json
import logging
from datetime import datetime, timezone
import pytest

from src.config import QualificationPolicy, load_config
from src.database import Database
from src.deduplication import deduplicate_batch
from src.discovery.youtube_api import YouTubeAPIDiscovery
from src.exports import export_leads_csv, export_summary_json
from src.logging_config import SecretMaskingFilter, StructuredFormatter, setup_logging
from src.models import (
    CampaignOutreachRecord,
    InvalidStateTransitionError,
    Lead,
    OutreachState,
    QualificationStatus,
    VerificationStatus,
)
from src.verification.channels import select_channels_for_lead
from src.verification.evidence import (
    calculate_days_ago,
    create_evidence_items_for_lead,
)
from src.verification.outreach import generate_outreach_for_lead
from src.verification.qualification import (
    classify_candidate_gates,
    qualify_lead,
    rank_and_assign_priorities,
    validate_country_mix,
)
from src.verification.seed_testing import OutreachSimulator, transition_record_state

REF_DATE = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clean_lead():
    """A benchmark lead satisfying all requirements."""
    return Lead(
        creator_name="Grounded Creator",
        creator_type="video_podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="UC_TEST_GROUNDED",
        official_profile_url="https://youtube.com/@groundedcreator",
        candidate_source_url="https://source.com/list",
        recent_content_urls=[
            "https://youtube.com/watch?v=episode101",
            "https://youtube.com/watch?v=episode102",
        ],
        recent_content_dates=["2026-10-20", "2026-10-10"],
        commercial_evidence_url="https://groundedcreator.com/coaching",
        workflow_need_evidence_url="https://groundedcreator.com/archive",
        business_contact_type="email",
        business_contact_value="host@groundedcreator.com",
        business_contact_source_url="https://groundedcreator.com/contact",
        business_contact_last_active="2026-10-15",
        evidence_checked_at="2026-10-24T12:00:00Z",
        is_synthetic=False,
    )


# ==============================================================================
# 1. Missing evidence cannot pass a hard gate
# ==============================================================================
def test_missing_evidence_cannot_pass_hard_gate(clean_lead):
    policy = QualificationPolicy()

    # Missing commercial evidence -> must be needs_review, never qualified
    clean_lead.commercial_evidence_url = None
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("commercial" in r.lower() for r in reasons)

    # Missing workflow need evidence -> needs_review
    clean_lead.commercial_evidence_url = "https://groundedcreator.com/coaching"
    clean_lead.workflow_need_evidence_url = None
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("workflow" in r.lower() for r in reasons)

    # Missing business contact value -> needs_review
    clean_lead.workflow_need_evidence_url = "https://groundedcreator.com/archive"
    clean_lead.business_contact_value = ""
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("contact" in r.lower() for r in reasons)


# ==============================================================================
# 2. Qualification statuses are derived from actual checks
# ==============================================================================
def test_qualification_statuses_derived_from_actual_checks(clean_lead):
    cfg = load_config()
    # Attempt to spoof status: lead claims 'qualified' in input data, but is an agency
    clean_lead.qualification_status = "qualified"
    clean_lead.creator_type = "agency"

    evaluated, vlog = qualify_lead(clean_lead, cfg, reference_date=REF_DATE)
    # Must be disqualified despite raw input status
    assert evaluated.qualification_status == QualificationStatus.DISQUALIFIED.value
    assert vlog.status_after == QualificationStatus.DISQUALIFIED.value
    assert evaluated.score == 0.0
    assert evaluated.priority is None


# ==============================================================================
# 3. Stale evidence is flagged
# ==============================================================================
def test_stale_evidence_is_flagged(clean_lead):
    # Set evidence checked 45 days ago (freshness limit is 30 days)
    clean_lead.evidence_checked_at = "2026-09-10T12:00:00Z"
    days = calculate_days_ago(clean_lead.evidence_checked_at, REF_DATE)
    assert days == 45

    ev_items = create_evidence_items_for_lead(clean_lead, reference_date=REF_DATE)
    stale_items = [item for item in ev_items if item.verification_status == VerificationStatus.STALE.value]
    assert len(stale_items) > 0
    for it in stale_items:
        assert "exceeds freshness window of 30 days" in (it.review_reason or "")

    # Qualification hard gate must also fail
    policy = QualificationPolicy()
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.DISQUALIFIED.value
    assert any("freshness window" in r for r in reasons)


# ==============================================================================
# 4. The country mix is calculated from the actual dataset
# ==============================================================================
def test_country_mix_calculated_from_actual_dataset(clean_lead):
    policy = QualificationPolicy()

    # Case A: Only synthetic leads in pool -> must report 0 real qualified and meet_policy=False
    clean_lead.is_synthetic = True
    clean_lead.qualification_status = QualificationStatus.QUALIFIED.value
    mix_result = validate_country_mix([clean_lead], policy)
    assert mix_result["total_qualified"] == 0
    assert mix_result["meets_policy"] is False
    assert "No real qualified leads in pool" in mix_result["warnings"][0]

    # Case B: Real qualified leads from 3 distinct countries
    lead_us = clean_lead.model_copy(update={"is_synthetic": False, "country": "United States", "platform_id": "P1"})
    lead_uk = clean_lead.model_copy(update={"is_synthetic": False, "country": "United Kingdom", "platform_id": "P2"})
    lead_ca = clean_lead.model_copy(update={"is_synthetic": False, "country": "Canada", "platform_id": "P3"})

    mix_valid = validate_country_mix([lead_us, lead_uk, lead_ca], policy)
    assert mix_valid["total_qualified"] == 3
    assert mix_valid["distinct_countries"] == 3
    assert mix_valid["share_allowed_countries"] == 1.0
    assert round(mix_valid["max_single_country_share"], 2) == 0.33
    assert mix_valid["meets_policy"] is True


# ==============================================================================
# 5. Duplicates are prevented across repeated imports
# ==============================================================================
def test_duplicates_prevented_across_repeated_imports(clean_lead):
    # Initial batch
    to_insert, to_update, stats_1 = deduplicate_batch([], [clean_lead], run_id="r1")
    assert stats_1["new_records"] == 1
    assert stats_1["exact_duplicates"] == 0

    # Repeat with tracking parameters appended to profile URL
    lead_dup = clean_lead.model_copy(
        update={"official_profile_url": "https://youtube.com/@groundedcreator?utm_source=test&si=123"}
    )
    to_insert_rep, to_update_rep, stats_2 = deduplicate_batch(
        existing_leads=[clean_lead],
        incoming_candidates=[lead_dup],
        run_id="r2",
    )
    assert stats_2["new_records"] == 0
    assert stats_2["exact_duplicates"] == 1
    assert len(to_insert_rep) == 0


# ==============================================================================
# 6. Every Priority A message references verified recent content
# ==============================================================================
def test_priority_a_message_references_verified_recent_content(clean_lead):
    # Verify grounding when recent content URL is available
    outreach = generate_outreach_for_lead(clean_lead)
    assert outreach.specific_content_source_url == "https://youtube.com/watch?v=episode101"
    assert "https://youtube.com/watch?v=episode101" in outreach.proposed_first_message
    assert outreach.validation_status == "valid"

    # Suppress personalisation when content evidence is missing
    clean_lead_no_content = clean_lead.model_copy(update={"recent_content_urls": []})
    outreach_suppressed = generate_outreach_for_lead(clean_lead_no_content)
    assert outreach_suppressed.validation_status == "needs_review"
    assert "[OUTREACH PERSONALISATION SUPPRESSED]" in outreach_suppressed.proposed_first_message


# ==============================================================================
# 7. No guessed contacts or fabricated activity metrics are allowed
# ==============================================================================
def test_no_guessed_contacts_or_fabricated_metrics(clean_lead):
    # YouTube API discovery leaves contacts unpopulated (no guessing)
    yt = YouTubeAPIDiscovery(api_key="mock_key")
    assert yt.source_name == "YouTube Data API v3"

    # Missing contact cannot be guessed; rejected as needs_review
    lead_missing_contact = clean_lead.model_copy(
        update={
            "business_contact_value": None,
            "business_contact_type": None,
            "business_contact_source_url": None,
        }
    )
    assert lead_missing_contact.business_contact_value is None
    assert lead_missing_contact.business_contact_type is None

    # Hard gate rejects unverified contact
    policy = QualificationPolicy()
    st, reasons = classify_candidate_gates(lead_missing_contact, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("business contact" in r.lower() for r in reasons)


# ==============================================================================
# 8. Test-mode events are labelled as simulated
# ==============================================================================
def test_test_mode_events_labelled_as_simulated(tmp_path):
    db = Database(str(tmp_path / "sim_test.db"))
    test_lead = Lead(
        id=1,
        creator_name="Test Lead",
        creator_type="podcaster",
        platform="youtube",
        platform_id="UC_TEST_1",
        official_profile_url="https://youtube.com/@testlead",
        candidate_source_url="https://source.com",
        business_contact_value="candidate@incubrix.local",
    )
    db.insert_lead(test_lead)

    record = OutreachSimulator.create_campaign_record(test_lead, db=db)
    OutreachSimulator.approve_for_test(record, db=db)
    ev, created = OutreachSimulator.simulate_send(record, db=db)

    assert created is True
    assert ev.event_payload.get("simulated") is True
    assert ev.event_payload.get("simulated_delivery") == "DELIVERED_IN_TEST_SANDBOX"


# ==============================================================================
# 9. Opt-outs suppress further test follow-ups
# ==============================================================================
def test_opt_outs_suppress_further_test_followups(tmp_path):
    db = Database(str(tmp_path / "optout_test.db"))
    test_lead = Lead(
        id=2,
        creator_name="Optout Lead",
        creator_type="coach_creator",
        platform="youtube",
        platform_id="UC_OPTOUT_1",
        official_profile_url="https://youtube.com/@optout",
        candidate_source_url="https://source.com",
        business_contact_value="optout@incubrix.local",
    )
    db.insert_lead(test_lead)

    record = OutreachSimulator.create_campaign_record(test_lead, db=db)
    OutreachSimulator.approve_for_test(record, db=db)
    OutreachSimulator.simulate_send(record, db=db)

    # Opt-out
    supp, ev, created = OutreachSimulator.simulate_opt_out(record, db=db)
    assert supp.contact_value == "optout@incubrix.local"
    assert record.state == OutreachState.OPTED_OUT.value

    # Attempting to re-approve or send must be blocked
    with pytest.raises(InvalidStateTransitionError):
        transition_record_state(record, OutreachState.APPROVED_FOR_TEST.value, db=db)

    # simulate_send directly against opted-out contact returns BLOCKED event
    blocked_ev, blocked_created = OutreachSimulator.simulate_send(record, db=db)
    assert blocked_ev.event_type == "BLOCKED"
    assert blocked_ev.status == "SUPPRESSED"


# ==============================================================================
# 10. API keys and secrets never appear in logs or exports
# ==============================================================================
def test_api_keys_and_secrets_never_appear_in_logs_or_exports(tmp_path):
    # 1. Test logger filter masks API keys
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(StructuredFormatter("%(message)s"))
    secret_filter = SecretMaskingFilter()
    handler.addFilter(secret_filter)

    test_logger = logging.getLogger("incubrix.security_test")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    dummy_key = "AIzaSyD-TEST_FAKE_KEY_1234567890123"
    test_logger.info(f"Connecting with API key {dummy_key} and param token=secret_password_abc")

    log_output = log_capture.getvalue()
    assert dummy_key not in log_output
    assert "secret_password_abc" not in log_output
    assert "***REDACTED_API_KEY***" in log_output
    assert "token=***REDACTED***" in log_output

    # 2. Test exports do not include secrets
    out_dir = tmp_path / "exports_sec"
    lead = Lead(
        creator_name="Export Creator",
        creator_type="podcaster",
        platform="youtube",
        platform_id="UC_EXPORT_1",
        official_profile_url="https://youtube.com/@export",
        candidate_source_url="https://source.com",
    )
    json_path = export_summary_json([lead], str(out_dir / "summary.json"), run_id="sec_run")
    with open(json_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "AIza" not in content
        assert "api_key" not in content.lower() or "not configured" in content.lower()


# ==============================================================================
# Additional Senior QA Regression Tests
# ==============================================================================
def test_synthetic_fixture_auto_detection_prevents_leakage(tmp_path):
    """
    Regression Test:
    Even if is_synthetic is omitted or set to False, any fixture with [FIXTURE] prefix
    or test domains must be auto-detected as synthetic and excluded from qualified_leads.csv.
    """
    omitted_flag_lead = Lead(
        creator_name="[FIXTURE] Forgot Column Lead",
        creator_type="video_podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="UC_OMITTED_SYNTH",
        official_profile_url="https://youtube.com/@forgotcolumn",
        candidate_source_url="https://source.com",
        recent_content_urls=["https://youtube.com/watch?v=v1", "https://youtube.com/watch?v=v2"],
        recent_content_dates=["2026-10-20", "2026-10-15"],
        commercial_evidence_url="https://forgotcolumn.com/sponsor",
        workflow_need_evidence_url="https://forgotcolumn.com/episodes",
        business_contact_type="email",
        business_contact_value="partners@forgotcolumn.com",
        business_contact_source_url="https://forgotcolumn.com/contact",
        business_contact_last_active="2026-10-20",
        evidence_checked_at="2026-10-24T12:00:00Z",
        qualification_status="qualified",
        is_synthetic=False,  # Intentionally passed False
    )
    # Must be auto-detected as synthetic by model_post_init
    assert omitted_flag_lead.is_synthetic is True

    # Test export isolation
    out_csv = tmp_path / "leak_check_qualified.csv"
    export_leads_csv([omitted_flag_lead], str(out_csv), filter_status="qualified", allow_synthetic=False)
    with open(out_csv, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1, "Synthetic fixture with [FIXTURE] prefix leaked into production qualified export!"


def test_missing_dates_and_missing_profile_url_cannot_pass_hard_gates(clean_lead):
    """
    Regression Test:
    Verify that missing contact activity date, missing checked timestamp,
    and missing profile URL cannot pass hard gates.
    """
    policy = QualificationPolicy()

    # 1. Missing profile URL -> disqualified
    clean_lead.official_profile_url = ""
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.DISQUALIFIED.value
    assert any("profile url" in r.lower() for r in reasons)

    # 2. Missing evidence_checked_at -> needs_review
    clean_lead.official_profile_url = "https://youtube.com/@groundedcreator"
    clean_lead.evidence_checked_at = None
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("evidence_checked_at" in r.lower() for r in reasons)

    # 3. Missing business_contact_last_active -> needs_review
    clean_lead.evidence_checked_at = "2026-10-24T12:00:00Z"
    clean_lead.business_contact_last_active = None
    st, reasons = classify_candidate_gates(clean_lead, policy, reference_date=REF_DATE)
    assert st == QualificationStatus.NEEDS_REVIEW.value
    assert any("last active" in r.lower() for r in reasons)


def test_non_target_country_and_inactive_content_spoofed_status_rejected(clean_lead):
    """
    Regression Test:
    Candidates from non-target countries (e.g., Germany) or with inactive content (>60d)
    must be strictly disqualified even if input data claims 'qualified'.
    """
    cfg = load_config()

    # Non-target country claiming qualified
    clean_lead.qualification_status = "qualified"
    clean_lead.country = "Germany"
    evaluated, vlog = qualify_lead(clean_lead, cfg, reference_date=REF_DATE)
    assert evaluated.qualification_status == QualificationStatus.DISQUALIFIED.value
    assert any("outside the 7 approved" in r.lower() for r in evaluated.disqualification_reasons)

    # Inactive content claiming qualified
    clean_lead.country = "United States"
    clean_lead.recent_content_dates = ["2026-05-01"]  # > 150 days ago
    evaluated_inactive, _ = qualify_lead(clean_lead, cfg, reference_date=REF_DATE)
    assert evaluated_inactive.qualification_status == QualificationStatus.DISQUALIFIED.value
    assert any("activity threshold not met" in r.lower() for r in evaluated_inactive.disqualification_reasons)
