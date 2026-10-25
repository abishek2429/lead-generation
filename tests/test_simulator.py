"""
Comprehensive tests for safe outreach tracking and reply-state simulator.

Validates:
1. Unique outreach record per lead and campaign.
2. State transitions across: draft, approved_for_test, sent_in_test, replied_in_test, opted_out, closed.
3. Invalid state transitions and event types raise appropriate exceptions.
4. Idempotency: duplicate event submissions do not duplicate records in SQLite.
5. Opt-out suppression: halted outreach and follow-up blocking.
6. Opaque tracking link generator: uses configured test base URL and contains zero PII.
7. Audit event logging includes UTC timestamp, campaign ID, test-account ID, and simulation markers.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.database import Database
from src.models import (
    CampaignOutreachRecord,
    DeliveryEvent,
    InvalidStateTransitionError,
    Lead,
    OutreachState,
    VALID_OUTREACH_STATES,
)
from src.verification.seed_testing import (
    OutreachSimulator,
    UnauthorizedEndpointError,
    contains_pii,
    generate_opaque_tracking_link,
    generate_opaque_tracking_token,
    transition_record_state,
)


@pytest.fixture
def test_db(tmp_path):
    """Provide an isolated, temporary SQLite database for testing."""
    db_file = tmp_path / "test_simulator.db"
    return Database(str(db_file))


@pytest.fixture
def sample_lead(test_db):
    """Create a sample qualified lead in the test database."""
    lead = Lead(
        id=1,
        creator_name="Dr. Andrew Huberman",
        creator_type="podcast_creator",
        platform="youtube",
        platform_id="hubermanlab_test",
        official_profile_url="https://youtube.com/@hubermanlab",
        candidate_source_url="https://youtube.com/@hubermanlab",
        business_contact_type="email",
        business_contact_value="candidate@incubrix.local",  # Safe test endpoint
        qualification_status="qualified",
        score=92.0,
        priority="A",
        is_synthetic=False,
    )
    return test_db.insert_lead(lead)


# ==============================================================================
# 1. UNIQUE OUTREACH RECORD PER LEAD AND CAMPAIGN
# ==============================================================================
def test_unique_outreach_record_per_lead_and_campaign(sample_lead, test_db):
    """Ensure unique record per (lead_id, campaign_id) and prevent duplicates."""
    camp_a = "spring_cohort_2026"
    camp_b = "summer_accelerator_2026"

    # Create record in Campaign A
    rec_a1 = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id=camp_a,
        channel="email",
        test_account_id="candidate@incubrix.local",
        db=test_db,
    )
    assert rec_a1.id is not None
    assert rec_a1.lead_id == sample_lead.id
    assert rec_a1.campaign_id == camp_a
    assert rec_a1.state == OutreachState.DRAFT.value

    # Create record for same lead in Campaign B (allowed)
    rec_b = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id=camp_b,
        channel="email",
        test_account_id="candidate@incubrix.local",
        db=test_db,
    )
    assert rec_b.id != rec_a1.id
    assert rec_b.campaign_id == camp_b

    # Attempting to re-create in Campaign A returns the existing record
    rec_a2 = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id=camp_a,
        channel="email",
        db=test_db,
    )
    assert rec_a2.id == rec_a1.id

    # Verify database count
    records_a = test_db.get_campaign_outreach_records(campaign_id=camp_a)
    assert len(records_a) == 1
    assert records_a[0].id == rec_a1.id


# ==============================================================================
# 2. STATE TRANSITIONS & LIFECYCLE TESTS
# ==============================================================================
def test_full_valid_state_lifecycle(sample_lead, test_db):
    """
    Test standard lifecycle progression:
    draft -> approved_for_test -> sent_in_test -> replied_in_test -> closed.
    """
    # 1. Draft
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="lifecycle_test",
        contact_endpoint="candidate@incubrix.local",
        db=test_db,
    )
    assert record.state == "draft"

    # 2. Approve for test
    record = OutreachSimulator.approve_for_test(record, db=test_db)
    assert record.state == "approved_for_test"
    db_rec = test_db.get_campaign_outreach_record(sample_lead.id, "lifecycle_test")
    assert db_rec.state == "approved_for_test"

    # 3. Sent in test
    ev_sent, created = OutreachSimulator.simulate_send(record, db=test_db)
    assert created is True
    assert ev_sent.event_type == "SENT"
    assert record.state == "sent_in_test"

    # 4. Replied in test
    ev_reply, created_reply = OutreachSimulator.simulate_interaction(
        opaque_id=record.opaque_id,
        event_type="REPLY",
        reply_text="Looks great! Let's schedule a call.",
        db=test_db,
    )
    assert created_reply is True
    assert ev_reply.event_type == "REPLY"
    db_rec = test_db.get_campaign_outreach_record(sample_lead.id, "lifecycle_test")
    assert db_rec.state == "replied_in_test"

    # 5. Closed
    record = OutreachSimulator.close_record(db_rec, notes="Call scheduled", db=test_db)
    assert record.state == "closed"
    db_rec_final = test_db.get_campaign_outreach_record(sample_lead.id, "lifecycle_test")
    assert db_rec_final.state == "closed"


def test_invalid_state_transitions_raise_error(sample_lead, test_db):
    """Attempting illegal transitions must raise InvalidStateTransitionError."""
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="illegal_trans_test",
        contact_endpoint="candidate@incubrix.local",
        db=test_db,
    )
    assert record.state == "draft"

    # Cannot jump directly from draft to sent_in_test (must be approved first)
    with pytest.raises(InvalidStateTransitionError):
        transition_record_state(record, OutreachState.SENT_IN_TEST.value, db=test_db)

    # Cannot jump directly from draft to replied_in_test
    with pytest.raises(InvalidStateTransitionError):
        transition_record_state(record, OutreachState.REPLIED_IN_TEST.value, db=test_db)

    # Unknown state string raises ValueError
    with pytest.raises(ValueError):
        transition_record_state(record, "unknown_custom_state", db=test_db)

    # Move to closed
    record = OutreachSimulator.close_record(record, db=test_db)
    assert record.state == "closed"

    # Closed is terminal: cannot transition from closed to draft or approved
    with pytest.raises(InvalidStateTransitionError):
        transition_record_state(record, OutreachState.DRAFT.value, db=test_db)


# ==============================================================================
# 3. IDEMPOTENCY & DUPLICATE EVENT TESTS
# ==============================================================================
def test_idempotency_duplicate_event_submissions(sample_lead, test_db):
    """Repeated event submissions with the same idempotent_key must not duplicate events."""
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="idempotency_camp",
        contact_endpoint="candidate@incubrix.local",
        db=test_db,
    )
    record = OutreachSimulator.approve_for_test(record, db=test_db)

    fixed_send_key = "idemp_send_001"

    # First send submission
    ev1, created1 = OutreachSimulator.simulate_send(
        record=record,
        idempotent_key=fixed_send_key,
        db=test_db,
    )
    assert created1 is True
    assert ev1.event_type == "SENT"
    initial_event_count = len(test_db.get_delivery_events())

    # Second send submission with identical key
    ev2, created2 = OutreachSimulator.simulate_send(
        record=record,
        idempotent_key=fixed_send_key,
        db=test_db,
    )
    assert created2 is False, "Duplicate event was incorrectly inserted as new!"
    assert ev2.id == ev1.id, "Duplicate submission did not return original event ID!"
    assert len(test_db.get_delivery_events()) == initial_event_count, "Event count increased despite idempotency key!"

    # Interaction idempotency test
    fixed_click_key = "idemp_click_002"
    click1, click_created1 = OutreachSimulator.simulate_interaction(
        opaque_id=record.opaque_id,
        event_type="CLICK",
        idempotent_key=fixed_click_key,
        db=test_db,
    )
    assert click_created1 is True

    click2, click_created2 = OutreachSimulator.simulate_interaction(
        opaque_id=record.opaque_id,
        event_type="CLICK",
        idempotent_key=fixed_click_key,
        db=test_db,
    )
    assert click_created2 is False
    assert click2.id == click1.id


# ==============================================================================
# 4. INVALID EVENTS HANDLING
# ==============================================================================
def test_invalid_event_types_rejected(sample_lead, test_db):
    """Unsupported interaction event types must be rejected."""
    token = generate_opaque_tracking_token()

    with pytest.raises(ValueError) as exc:
        OutreachSimulator.simulate_interaction(
            opaque_id=token,
            event_type="PURCHASED_SUBSCRIPTION",
            db=test_db,
        )
    assert "Invalid interaction event type" in str(exc.value)


# ==============================================================================
# 5. OPT-OUT HANDLING & SUPPRESSION TESTS
# ==============================================================================
def test_opt_out_suppresses_further_followups(sample_lead, test_db):
    """
    Opt-out must:
    1. Add contact to suppression list.
    2. Transition campaign outreach record to opted_out.
    3. Block subsequent send simulations to that contact.
    4. Reject illegal transitions back to approved or sent.
    """
    test_contact = "candidate@incubrix.local"
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="opt_out_camp",
        contact_endpoint=test_contact,
        db=test_db,
    )
    record = OutreachSimulator.approve_for_test(record, db=test_db)
    OutreachSimulator.simulate_send(record, db=test_db)

    # Creator opts out
    supp, ev_opt, created = OutreachSimulator.simulate_opt_out(
        contact_or_record=record,
        reason="Recipient replied 'unsubscribe'",
        db=test_db,
    )
    assert supp.contact_value == test_contact
    assert test_db.is_contact_suppressed(test_contact, "email") is True
    assert record.state == "opted_out"

    # Attempting to send follow-up must be blocked and recorded as BLOCKED/SUPPRESSED
    blocked_ev, _ = OutreachSimulator.simulate_send(
        record=record,
        db=test_db,
    )
    assert blocked_ev.status == "SUPPRESSED"
    assert blocked_ev.event_type == "BLOCKED"

    # Attempting to manually transition opted_out back to approved_for_test must raise error
    with pytest.raises(InvalidStateTransitionError):
        transition_record_state(record, OutreachState.APPROVED_FOR_TEST.value, db=test_db)


# ==============================================================================
# 6. TRACKING LINK GENERATION & ZERO PII VERIFICATION
# ==============================================================================
def test_tracking_link_generation_opaque_and_no_pii(sample_lead):
    """
    Tracking link generator MUST use configured test base URL and opaque ID.
    Must NEVER leak personal information (email, names, handles, lead IDs) in URLs.
    """
    base_url = "http://localhost:8501"
    token, link = generate_opaque_tracking_link(base_url=base_url)

    import urllib.parse
    parsed = urllib.parse.urlparse(link)
    params = urllib.parse.parse_qs(parsed.query)

    # URL query parameter must ONLY contain 'trk' with the opaque token
    assert list(params.keys()) == ["trk"]
    assert params["trk"] == [token]

    # No query parameters for lead, id, touch, name, or email
    assert "lead" not in params
    assert "lead_id" not in params
    assert "touch" not in params
    assert "email" not in params
    assert "name" not in params

    # Opaque token must be a clean hex or url-safe string without personal markers
    assert len(token) >= 16
    assert ":" not in token  # Not colon-separated lead ID

    # Verify zero PII in link
    prohibited = [
        sample_lead.creator_name,
        sample_lead.business_contact_value,
        "huberman",
        "andrew",
        "@",
    ]
    assert contains_pii(link, prohibited_values=prohibited) is False
    assert "@" not in link


# ==============================================================================
# 7. EVENT LOGGING FIELDS AUDIT
# ==============================================================================
def test_event_logging_utc_timestamp_campaign_and_test_account(sample_lead, test_db):
    """Every delivery and interaction event must log UTC timestamp, campaign ID, and test account ID."""
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="audit_camp_2026",
        contact_endpoint="candidate@incubrix.local",
        test_account_id="growth_tester_01",
        db=test_db,
    )
    record = OutreachSimulator.approve_for_test(record, test_account_id="growth_tester_01", db=test_db)

    ev, _ = OutreachSimulator.simulate_send(
        record=record,
        test_account_id="growth_tester_01",
        db=test_db,
    )

    assert ev.campaign_id == "audit_camp_2026"
    assert ev.test_account_id == "growth_tester_01"
    assert ev.timestamp is not None
    # Verify timestamp parses as valid ISO UTC
    dt = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
    assert dt.tzinfo is not None

    # Summary metrics must correctly mark simulated test data
    summary = OutreachSimulator.get_campaign_summary(campaign_id="audit_camp_2026", db=test_db)
    assert summary["is_simulated_test_data"] is True
    assert summary["data_label"] == "TEST DATA / SIMULATION ONLY"
    assert summary["sent_count"] == 1


# ==============================================================================
# 8. LOCAL HTTP TEST ENDPOINTS HARNESS TEST
# ==============================================================================
def test_http_simulator_endpoints(sample_lead, test_db):
    """Test local HTTP simulator server endpoints."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from src.simulator_server import SimulatorRequestHandler

    # Seed record
    record = OutreachSimulator.create_campaign_record(
        lead=sample_lead,
        campaign_id="http_test_camp",
        contact_endpoint="candidate@incubrix.local",
        db=test_db,
    )
    OutreachSimulator.approve_for_test(record, db=test_db)

    class CustomHandler(SimulatorRequestHandler):
        db = test_db

    server = HTTPServer(("127.0.0.1", 0), CustomHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. Health check
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["mode"] == "SIMULATION_TEST_ONLY"

        # 2. Simulate send via POST
        send_payload = json.dumps({
            "lead_id": sample_lead.id,
            "campaign_id": "http_test_camp",
            "test_account_id": "candidate_http_tester",
            "idempotent_key": "http_send_key_1",
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/simulate/send",
            data=send_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["event_type"] == "SENT"
            assert data["created"] is True
            opaque_id = data["opaque_id"]

        # 3. Simulate tracking click via GET /track?id=<opaque_id>
        with urllib.request.urlopen(f"{base_url}/track?id={opaque_id}") as resp:
            assert resp.status == 200
            html = resp.read().decode()
            assert "SIMULATED CLICK RECORDED" in html

        # 4. Simulate reply via POST /api/simulate/reply
        reply_payload = json.dumps({
            "opaque_id": opaque_id,
            "reply_text": "HTTP reply simulation received.",
            "test_account_id": "candidate_http_tester",
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/simulate/reply",
            data=reply_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["event_type"] == "REPLY"

        # 5. Check stats via GET /api/simulate/stats
        with urllib.request.urlopen(f"{base_url}/api/simulate/stats?campaign_id=http_test_camp") as resp:
            assert resp.status == 200
            stats = json.loads(resp.read().decode())
            assert stats["is_simulated_test_data"] is True
            assert stats["replied_count"] == 1

        # 6. Opt-out via POST /api/simulate/opt-out
        opt_payload = json.dumps({
            "contact": "candidate@incubrix.local",
            "campaign_id": "http_test_camp",
            "reason": "Test opt out",
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/simulate/opt-out",
            data=opt_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["suppressed"] is True

    finally:
        server.shutdown()
        server.server_close()
