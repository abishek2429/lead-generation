"""
Safe seed testing and delivery simulation sandbox for IncuBrix Outreach Engine.

SAFETY GUARANTEE:
- Operates ONLY on authorized candidate-controlled contact endpoints or test seeds.
- Never sends messages to real creators.
- Does not claim delivery, opens, clicks, or replies unless actually executed in this authorized test harness.
- Includes tracking link generation, delivery simulation, reply event logging, opt-out suppression,
  and follow-up state transition machine.
"""

from __future__ import annotations

import base64
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from src.models import (
    CampaignOutreachRecord,
    DeliveryEvent,
    InvalidStateTransitionError,
    Lead,
    OutreachPreparation,
    OutreachState,
    SuppressionRecord,
    VALID_OUTREACH_STATES,
    VALID_STATE_TRANSITIONS,
    current_utc_iso,
)
from src.database import (
    Database,
    add_to_suppression_list,
    get_campaign_outreach_record,
    get_campaign_outreach_record_by_opaque_id,
    get_campaign_outreach_records,
    get_delivery_event_by_idempotent_key,
    get_delivery_events,
    get_outreach_preparation_by_platform_id,
    get_suppression_list,
    is_contact_suppressed,
    log_delivery_event,
    log_idempotent_event,
    save_campaign_outreach_record,
    update_campaign_outreach_record,
    update_outreach_preparation,
)
from src.logging_config import get_logger

logger = get_logger("seed_testing")

# Permitted test domains and specific candidate-controlled endpoints
AUTHORIZED_TEST_DOMAINS = (
    "@incubrix.local",
    "@example.com",
    "@test.local",
    "@candidate.test",
    "@localhost",
)

AUTHORIZED_TEST_ENDPOINTS = (
    "growth.engineer.candidate@gmail.com",
    "candidate@incubrix.local",
    "test@incubrix.local",
    "growth.candidate@incubrix.local",
    "https://linkedin.com/in/incubrix-candidate-test",
    "https://instagram.com/incubrix_candidate_test",
)


class UnauthorizedEndpointError(ValueError):
    """Raised when an outreach test is attempted against an unauthorized real creator contact."""
    pass


def is_authorized_test_endpoint(contact_value: str) -> bool:
    """Check if the contact endpoint is authorized for safe seed testing."""
    if not contact_value:
        return False
    val = contact_value.strip().lower()
    if val in [e.lower() for e in AUTHORIZED_TEST_ENDPOINTS]:
        return True
    return any(val.endswith(domain) for domain in AUTHORIZED_TEST_DOMAINS)


def generate_tracking_token(lead_id: Optional[int], touch_number: int) -> str:
    """Generate a deterministic, secure tracking token for email/link interaction."""
    lid_str = str(lead_id or "0")
    raw = f"{lid_str}:{touch_number}:{uuid.uuid4().hex[:8]}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def generate_tracking_link(
    lead_id: Optional[int],
    touch_number: int,
    base_url: str = "http://localhost:8501",
) -> Tuple[str, str]:
    """Generate a tracking token and simulated tracking URL on localhost."""
    token = generate_tracking_token(lead_id, touch_number)
    link = f"{base_url}/?action=track&token={token}&lead={lead_id or 0}&touch={touch_number}"
    return token, link


def generate_opaque_tracking_token() -> str:
    """Generate an unguessable, cryptographically secure opaque token containing zero PII."""
    return uuid.uuid4().hex


def generate_opaque_tracking_link(
    base_url: str = "http://localhost:8501",
    opaque_id: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Generate an opaque tracking ID and a clean tracking URL.
    SAFETY GUARANTEE:
    - Uses only the configured test base URL and the opaque token.
    - Zero personal information in tracking URLs (no email, name, handle, or numeric lead ID).
    """
    token = opaque_id or generate_opaque_tracking_token()
    clean_base = base_url.rstrip("/")
    url = f"{clean_base}/?trk={token}"
    return token, url


def contains_pii(url: str, prohibited_values: Optional[List[str]] = None) -> bool:
    """
    Scan a URL to verify that zero personally identifiable information is exposed.
    Returns True if an email address, disallowed query parameters, or candidate names are detected.
    """
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    # Check query keys and values
    for k, v in params.items():
        if k not in ("trk", "id", "action"):
            return True
        for val in v:
            if "@" in val or "://" in val:
                return True

    if prohibited_values:
        url_lower = url.lower()
        for p in prohibited_values:
            if p and len(p) >= 3 and p.lower() in url_lower:
                return True
    return False


def transition_record_state(
    record: CampaignOutreachRecord,
    target_state: str,
    db: Optional[Database] = None,
    test_account_id: str = "candidate_test_account",
    notes: Optional[str] = None,
) -> CampaignOutreachRecord:
    """
    Execute a validated state transition on a CampaignOutreachRecord.
    Enforces valid state transition graph:
    - draft -> approved_for_test -> sent_in_test -> replied_in_test -> closed
    - Any active state -> opted_out -> closed
    Raises InvalidStateTransitionError if transition is illegal.
    """
    target = target_state.strip().lower()
    current = record.state.strip().lower()

    if target not in VALID_OUTREACH_STATES:
        raise ValueError(
            f"Unknown outreach state '{target_state}'. Valid states: {sorted(list(VALID_OUTREACH_STATES))}"
        )

    if target == current:
        return record

    allowed = VALID_STATE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Invalid state transition: Cannot transition record from '{current}' to '{target}'. "
            f"Allowed next states from '{current}': {sorted(list(allowed)) if allowed else 'None (terminal closed)'}."
        )

    # Check suppression if moving to approved_for_test or sent_in_test
    if target in (OutreachState.APPROVED_FOR_TEST.value, OutreachState.SENT_IN_TEST.value):
        if is_contact_suppressed(record.contact_endpoint, record.channel, db=db):
            raise InvalidStateTransitionError(
                f"Contact '{record.contact_endpoint}' is opted out and on the suppression list. "
                f"Cannot transition to '{target}'."
            )

    record.state = target
    record.updated_at = current_utc_iso()
    if notes:
        record.notes = notes
    record.test_account_id = test_account_id

    # Persist in DB
    updated = save_campaign_outreach_record(record, db=db)

    # Log status change event in delivery_events
    ev = DeliveryEvent(
        lead_id=record.lead_id,
        platform_id=record.platform_id,
        creator_name=record.creator_name,
        channel=record.channel,
        touch_number=1,
        event_type="STATUS_CHANGE",
        status="SUCCESS",
        campaign_id=record.campaign_id,
        test_account_id=test_account_id,
        opaque_id=record.opaque_id,
        recipient_contact=record.contact_endpoint,
        event_payload={"from_state": current, "to_state": target, "notes": notes or ""},
        timestamp=current_utc_iso(),
    )
    log_delivery_event(ev, db=db)

    return updated


class OutreachSimulator:
    """
    Controlled safe outreach tracking and reply-state simulator.
    Operates strictly in simulation mode with authorized test accounts.
    """

    @staticmethod
    def create_campaign_record(
        lead: Lead,
        campaign_id: str = "default_test_campaign",
        channel: str = "email",
        contact_endpoint: Optional[str] = None,
        test_account_id: str = "candidate_test_account",
        db: Optional[Database] = None,
    ) -> CampaignOutreachRecord:
        """Create or retrieve unique campaign outreach record for (lead_id, campaign_id)."""
        if lead.id is None:
            raise ValueError("Lead must have a valid integer id to create a campaign outreach record.")

        existing = get_campaign_outreach_record(lead.id, campaign_id, db=db)
        if existing:
            return existing

        # Ensure contact endpoint is an authorized test endpoint
        endpoint = (contact_endpoint or lead.business_contact_value or "").strip()
        if not is_authorized_test_endpoint(endpoint):
            # Safety fallback to candidate test sandbox
            endpoint = "candidate@incubrix.local"

        token, _ = generate_opaque_tracking_link()

        record = CampaignOutreachRecord(
            lead_id=lead.id,
            campaign_id=campaign_id,
            platform_id=lead.platform_id,
            creator_name=lead.creator_name or "Test Creator",
            channel=channel,
            contact_endpoint=endpoint,
            state=OutreachState.DRAFT.value,
            tracking_token=token,
            opaque_id=token,
            test_account_id=test_account_id,
            notes="Initial draft for simulation testing",
            created_at=current_utc_iso(),
            is_synthetic=lead.is_synthetic,
        )
        return save_campaign_outreach_record(record, db=db)

    @staticmethod
    def approve_for_test(
        record: CampaignOutreachRecord,
        test_account_id: str = "candidate_test_account",
        notes: Optional[str] = "Approved for local test harness",
        db: Optional[Database] = None,
    ) -> CampaignOutreachRecord:
        """Transition record from draft to approved_for_test."""
        return transition_record_state(
            record,
            OutreachState.APPROVED_FOR_TEST.value,
            db=db,
            test_account_id=test_account_id,
            notes=notes,
        )

    @staticmethod
    def simulate_send(
        record: CampaignOutreachRecord,
        test_account_id: str = "candidate_test_account",
        base_url: str = "http://localhost:8501",
        idempotent_key: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> Tuple[DeliveryEvent, bool]:
        """
        Simulate safe sending of outreach.
        Guarantees:
        - Rejects unauthorized real creator contacts.
        - Suppresses sending if contact is opted out.
        - Enforces that state must be approved_for_test.
        - Generates opaque tracking link without PII.
        - Ensures idempotency via idempotent_key.
        """
        endpoint = record.contact_endpoint
        if not is_authorized_test_endpoint(endpoint):
            raise UnauthorizedEndpointError(
                f"SAFETY VIOLATION: '{endpoint}' is not an authorized test endpoint."
            )

        # Idempotency check: if already submitted with this key, return existing record
        if idempotent_key:
            existing_event = get_delivery_event_by_idempotent_key(idempotent_key, db=db)
            if existing_event:
                logger.debug(f"Idempotent send already executed for key '{idempotent_key}'.")
                return existing_event, False

        # Check suppression list
        if is_contact_suppressed(endpoint, record.channel, db=db):
            blocked_event = DeliveryEvent(
                lead_id=record.lead_id,
                platform_id=record.platform_id,
                campaign_id=record.campaign_id,
                test_account_id=test_account_id,
                idempotent_key=idempotent_key,
                opaque_id=record.opaque_id,
                recipient_contact=endpoint,
                creator_name=record.creator_name,
                channel=record.channel,
                touch_number=1,
                event_type="BLOCKED",
                status="SUPPRESSED",
                event_payload={"reason": "Recipient is on the opt-out suppression list.", "simulated": True},
                timestamp=current_utc_iso(),
            )
            logged_event, created = log_idempotent_event(blocked_event, db=db)
            return logged_event, created

        # Enforce valid state for send
        if record.state != OutreachState.APPROVED_FOR_TEST.value:
            raise InvalidStateTransitionError(
                f"Cannot send outreach: Record {record.id} is in state '{record.state}', but must be 'approved_for_test'."
            )

        token = record.opaque_id or generate_opaque_tracking_token()
        _, tracking_link = generate_opaque_tracking_link(base_url, token)
        record.opaque_id = token
        record.tracking_token = token

        idem_key = idempotent_key or f"{record.campaign_id}:send:{record.lead_id}:{token}"

        event = DeliveryEvent(
            lead_id=record.lead_id,
            platform_id=record.platform_id,
            campaign_id=record.campaign_id,
            test_account_id=test_account_id,
            idempotent_key=idem_key,
            opaque_id=token,
            recipient_contact=endpoint,
            creator_name=record.creator_name,
            channel=record.channel,
            touch_number=1,
            event_type="SENT",
            status="SUCCESS",
            tracking_token=token,
            event_payload={
                "tracking_link": tracking_link,
                "simulated_delivery": "DELIVERED_IN_TEST_SANDBOX",
                "simulated": True,
            },
            timestamp=current_utc_iso(),
        )

        logged_event, created = log_idempotent_event(event, db=db)

        if created:
            record.state = OutreachState.SENT_IN_TEST.value
            record.updated_at = current_utc_iso()
            record.test_account_id = test_account_id
            save_campaign_outreach_record(record, db=db)
            logger.info(f"Simulated send for lead {record.lead_id} in campaign {record.campaign_id}.")

        return logged_event, created

    @staticmethod
    def simulate_interaction(
        opaque_id: str,
        event_type: str = "CLICK",
        test_account_id: str = "candidate_test_account",
        reply_text: Optional[str] = None,
        idempotent_key: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> Tuple[DeliveryEvent, bool]:
        """
        Log simulated interaction event (CLICK, OPEN, REPLY) using opaque tracking token.
        Guarantees idempotency and state transition to replied_in_test when reply occurs.
        """
        ev_type = event_type.upper().strip()
        if ev_type in ("CLICKED", "CLICK"):
            ev_type = "CLICK"
        elif ev_type in ("OPENED", "OPEN"):
            ev_type = "OPEN"
        elif ev_type in ("REPLIED", "REPLY"):
            ev_type = "REPLY"
        else:
            raise ValueError(f"Invalid interaction event type: '{event_type}'. Must be CLICK, OPEN, or REPLY.")

        record = get_campaign_outreach_record_by_opaque_id(opaque_id, db=db)
        lead_id = record.lead_id if record else None
        platform_id = record.platform_id if record else "seed_test"
        creator_name = record.creator_name if record else "Test Creator"
        channel = record.channel if record else "email"
        endpoint = record.contact_endpoint if record else "candidate@incubrix.local"
        camp_id = record.campaign_id if record else "default_test_campaign"

        idem_key = idempotent_key or f"{camp_id}:{ev_type}:{opaque_id}"

        payload: Dict[str, Any] = {"token": opaque_id, "simulated": True}
        if reply_text:
            payload["reply_text"] = reply_text

        event = DeliveryEvent(
            lead_id=lead_id,
            platform_id=platform_id,
            campaign_id=camp_id,
            test_account_id=test_account_id,
            idempotent_key=idem_key,
            opaque_id=opaque_id,
            recipient_contact=endpoint,
            creator_name=creator_name,
            channel=channel,
            touch_number=1,
            event_type=ev_type,
            status="SUCCESS",
            tracking_token=opaque_id,
            event_payload=payload,
            timestamp=current_utc_iso(),
        )

        logged_event, created = log_idempotent_event(event, db=db)

        if created and record:
            if ev_type == "REPLY" and record.state == OutreachState.SENT_IN_TEST.value:
                record.state = OutreachState.REPLIED_IN_TEST.value
                record.updated_at = current_utc_iso()
                record.test_account_id = test_account_id
                save_campaign_outreach_record(record, db=db)
                logger.info(f"Record {record.id} transitioned to replied_in_test.")

        return logged_event, created

    @staticmethod
    def simulate_opt_out(
        contact_or_record: Any,
        channel: str = "email",
        campaign_id: str = "default_test_campaign",
        test_account_id: str = "candidate_test_account",
        reason: str = "Opt-out requested (simulated)",
        idempotent_key: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> Tuple[SuppressionRecord, DeliveryEvent, bool]:
        """
        Process simulated opt-out.
        Guarantees:
        - Contact added to global suppression list.
        - Campaign record transitioned to opted_out.
        - Subsequent follow-up attempts are blocked.
        - Event logged with idempotency check.
        """
        record: Optional[CampaignOutreachRecord] = None
        if isinstance(contact_or_record, CampaignOutreachRecord):
            record = contact_or_record
            contact_val = record.contact_endpoint
            channel = record.channel
            campaign_id = record.campaign_id
        else:
            contact_val = str(contact_or_record)

        clean_contact = contact_val.strip().lower()

        # Add to suppression list
        suppression = add_to_suppression_list(
            contact_value_or_record=clean_contact,
            channel=channel,
            reason=reason,
            db=db,
        )

        idem_key = idempotent_key or f"{campaign_id}:opt_out:{clean_contact}"

        lead_id = record.lead_id if record else None
        platform_id = record.platform_id if record else "opt_out"
        creator_name = record.creator_name if record else "Opted Out Creator"

        event = DeliveryEvent(
            lead_id=lead_id,
            platform_id=platform_id,
            campaign_id=campaign_id,
            test_account_id=test_account_id,
            idempotent_key=idem_key,
            opaque_id=record.opaque_id if record else None,
            recipient_contact=clean_contact,
            creator_name=creator_name,
            channel=channel,
            touch_number=0,
            event_type="OPT_OUT",
            status="SUPPRESSED",
            event_payload={"reason": reason, "simulated": True},
            timestamp=current_utc_iso(),
        )

        logged_event, created = log_idempotent_event(event, db=db)

        if record and record.state != OutreachState.CLOSED.value:
            record.state = OutreachState.OPTED_OUT.value
            record.notes = reason
            record.updated_at = current_utc_iso()
            record.test_account_id = test_account_id
            save_campaign_outreach_record(record, db=db)

        return suppression, logged_event, created

    @staticmethod
    def close_record(
        record: CampaignOutreachRecord,
        test_account_id: str = "candidate_test_account",
        notes: Optional[str] = "Campaign completed and closed",
        db: Optional[Database] = None,
    ) -> CampaignOutreachRecord:
        """Transition record to terminal closed state."""
        return transition_record_state(
            record,
            OutreachState.CLOSED.value,
            db=db,
            test_account_id=test_account_id,
            notes=notes,
        )

    @staticmethod
    def get_campaign_summary(
        campaign_id: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate simulation metrics for reporting and dashboard display.
        Strictly labels all data as simulated test metrics.
        """
        records = get_campaign_outreach_records(campaign_id=campaign_id, db=db)
        events = get_delivery_events(limit=500, db=db)
        if campaign_id:
            events = [e for e in events if e.campaign_id == campaign_id]

        state_counts: Dict[str, int] = {s.value: 0 for s in OutreachState}
        for r in records:
            state_counts[r.state] = state_counts.get(r.state, 0) + 1

        event_counts: Dict[str, int] = {
            "SENT": 0,
            "OPEN": 0,
            "CLICK": 0,
            "REPLY": 0,
            "OPT_OUT": 0,
            "BLOCKED": 0,
            "STATUS_CHANGE": 0,
        }
        for e in events:
            etype = e.event_type.upper()
            if etype in ("CLICKED", "CLICK"):
                event_counts["CLICK"] += 1
            elif etype in ("OPENED", "OPEN"):
                event_counts["OPEN"] += 1
            elif etype in ("REPLIED", "REPLY"):
                event_counts["REPLY"] += 1
            elif etype in event_counts:
                event_counts[etype] += 1

        return {
            "campaign_id": campaign_id or "all_campaigns",
            "is_simulated_test_data": True,
            "data_label": "TEST DATA / SIMULATION ONLY",
            "total_records": len(records),
            "draft_count": state_counts[OutreachState.DRAFT.value],
            "approved_count": state_counts[OutreachState.APPROVED_FOR_TEST.value],
            "sent_count": state_counts[OutreachState.SENT_IN_TEST.value],
            "replied_count": state_counts[OutreachState.REPLIED_IN_TEST.value],
            "opted_out_count": state_counts[OutreachState.OPTED_OUT.value],
            "closed_count": state_counts[OutreachState.CLOSED.value],
            "event_counts": event_counts,
            "simulated_sends": event_counts["SENT"],
            "simulated_clicks": event_counts["CLICK"],
            "simulated_replies": event_counts["REPLY"],
            "opt_outs": event_counts["OPT_OUT"],
        }


class SeedSimulator:
    """Safe seed testing simulator for message verification, delivery, and lifecycle transitions."""

    @staticmethod
    def simulate_send(
        lead: Lead,
        prep: OutreachPreparation,
        touch_number: int = 1,
        forced_test_recipient: Optional[str] = None,
        base_url: str = "http://localhost:8501",
        db: Optional[Database] = None,
    ) -> DeliveryEvent:
        """
        Simulate safe sending of touch 1, 2, or 3.
        If lead contact is not an authorized test endpoint, forced_test_recipient MUST be provided.
        """
        recipient = (forced_test_recipient or prep.primary_contact_value or "").strip()

        # Strict safety check
        if not is_authorized_test_endpoint(recipient):
            raise UnauthorizedEndpointError(
                f"SAFETY VIOLATION: '{recipient}' is not an authorized seed testing endpoint. "
                f"Outreach simulation can only run on accounts owned/controlled by the candidate "
                f"(e.g. {', '.join(AUTHORIZED_TEST_DOMAINS)})."
            )

        # Check suppression list
        if is_contact_suppressed(recipient, prep.primary_channel, db=db):
            event = DeliveryEvent(
                lead_id=lead.id,
                platform_id=lead.platform_id,
                creator_name=lead.creator_name or "Creator",
                touch_number=touch_number,
                channel=prep.primary_channel,
                recipient=recipient,
                event_type="BLOCKED",
                status="SUPPRESSED",
                metadata={"reason": "Recipient is on the opt-out suppression list."},
            )
            log_delivery_event(event, db=db)
            return event

        token, tracking_link = generate_tracking_link(lead.id, touch_number, base_url)

        # Log simulated sent event
        event = DeliveryEvent(
            lead_id=lead.id,
            platform_id=lead.platform_id,
            creator_name=lead.creator_name or "Creator",
            touch_number=touch_number,
            channel=prep.primary_channel,
            recipient=recipient,
            event_type="SENT",
            status="SUCCESS",
            tracking_token=token,
            metadata={
                "tracking_link": tracking_link,
                "subject": prep.subject_line,
                "simulated_delivery": "DELIVERED_IN_TEST_SANDBOX",
            },
        )
        log_delivery_event(event, db=db)

        # Update OutreachPreparation status in database
        status_map = {1: "TOUCH_1_SENT", 2: "TOUCH_2_SENT", 3: "TOUCH_3_SENT"}
        new_status = status_map.get(touch_number, "SIMULATED_SENT")
        prep.outreach_status = new_status
        update_outreach_preparation(prep, db=db)

        logger.info(f"Simulated send for lead {lead.id} touch {touch_number} to {recipient}.")
        return event

    @staticmethod
    def simulate_interaction(
        token: str,
        event_type: str,  # 'OPENED', 'CLICKED', 'REPLIED'
        reply_text: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> Optional[DeliveryEvent]:
        """Log simulated interaction event (open, click, or reply) for a tracking token."""
        ev_type = event_type.upper()
        if ev_type not in ("OPENED", "CLICKED", "REPLIED"):
            raise ValueError(f"Invalid interaction event type: {event_type}")

        # Find existing delivery event
        existing_events = get_delivery_events(db=db)
        parent = next((e for e in existing_events if e.tracking_token == token), None)

        lead_id = parent.lead_id if parent else None
        platform_id = parent.platform_id if parent else "seed_test"
        creator_name = parent.creator_name if parent else "Test Creator"
        channel = parent.channel if parent else "email"
        recipient = parent.recipient if parent else "candidate@incubrix.local"
        touch_num = parent.touch_number if parent else 1

        meta: Dict[str, Any] = {"token": token}
        if reply_text:
            meta["reply_text"] = reply_text

        event = DeliveryEvent(
            lead_id=lead_id,
            platform_id=platform_id,
            creator_name=creator_name,
            touch_number=touch_num,
            channel=channel,
            recipient=recipient,
            event_type=ev_type,
            status="SUCCESS",
            tracking_token=token,
            metadata=meta,
        )
        log_delivery_event(event, db=db)

        # Update OutreachPreparation status
        db_prep = get_outreach_preparation_by_platform_id(platform_id, db=db)
        if db_prep:
            if ev_type == "REPLIED":
                db_prep.outreach_status = "REPLIED"
            elif ev_type == "CLICKED" and db_prep.outreach_status != "REPLIED":
                db_prep.outreach_status = "CLICKED"
            elif ev_type == "OPENED" and db_prep.outreach_status not in ("REPLIED", "CLICKED"):
                db_prep.outreach_status = "OPENED"
            update_outreach_preparation(db_prep, db=db)

        return event

    @staticmethod
    def handle_opt_out(
        contact_value: str,
        channel: str,
        reason: str = "Creator requested opt-out (replied 'stop')",
        lead_id: Optional[str] = None,
        db: Optional[Database] = None,
    ) -> SuppressionRecord:
        """Process an opt-out request and add to permanent suppression list."""
        suppression = SuppressionRecord(
            contact_value=contact_value.strip().lower(),
            channel=channel.strip().lower(),
            reason=reason,
            source="seed_testing_sandbox",
        )
        add_to_suppression_list(suppression, db=db)

        int_lead_id = None
        plat_id = "opt_out"
        if lead_id:
            if isinstance(lead_id, int):
                int_lead_id = lead_id
            elif str(lead_id).isdigit():
                int_lead_id = int(lead_id)
            else:
                plat_id = str(lead_id)

        # Log event
        event = DeliveryEvent(
            lead_id=int_lead_id,
            platform_id=plat_id,
            creator_name="Opted Out Recipient",
            touch_number=0,
            channel=channel,
            recipient=contact_value,
            event_type="OPT_OUT",
            status="SUPPRESSED",
            metadata={"reason": reason},
        )
        log_delivery_event(event, db=db)

        if lead_id:
            db_prep = get_outreach_preparation_by_platform_id(plat_id, db=db)
            if db_prep:
                db_prep.outreach_status = "OPTED_OUT"
                update_outreach_preparation(db_prep, db=db)

        logger.info(f"Contact {contact_value} successfully added to suppression list for channel {channel}.")
        return suppression

    @staticmethod
    def get_lead_state_history(lead_id: str, db: Optional[Database] = None) -> List[DeliveryEvent]:
        """Fetch chronological delivery and interaction history for a lead."""
        all_events = get_delivery_events(platform_id=lead_id, db=db)
        return sorted(all_events, key=lambda x: x.created_at or x.timestamp)

