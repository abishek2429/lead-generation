"""
Unit tests for SQLite database persistence and audit logs.
"""

import tempfile
from pathlib import Path
import pytest
from src.database import Database
from src.models import Lead, QualificationStatus, VerificationLog


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_leads.db"
        db = Database(str(db_file))
        yield db


def test_database_auto_initialization(temp_db):
    # Verify tables exist by inserting and retrieving
    metrics = temp_db.get_metrics()
    assert metrics["total_candidates"] == 0
    assert metrics["qualified"] == 0


def test_insert_and_get_lead(temp_db):
    lead = Lead(
        creator_name="Test DB Creator",
        creator_type="podcaster",
        country="Canada",
        platform="youtube",
        platform_id="UC_TEST_DB",
        official_profile_url="https://youtube.com/@testdb",
        candidate_source_url="https://source.com",
    )
    inserted = temp_db.insert_lead(lead)
    assert inserted.id is not None

    fetched = temp_db.get_lead_by_id(inserted.id)
    assert fetched is not None
    assert fetched.creator_name == "Test DB Creator"
    assert fetched.platform_id == "UC_TEST_DB"
    assert fetched.country == "Canada"

    by_pid = temp_db.get_lead_by_platform_id("youtube", "uc_test_db")
    assert by_pid is not None
    assert by_pid.id == inserted.id


def test_update_lead(temp_db):
    lead = Lead(
        creator_name="Original Name",
        creator_type="consultant_creator",
        country="Australia",
        platform="youtube",
        platform_id="UC_UPDATE_ME",
        official_profile_url="https://youtube.com/@updateme",
        candidate_source_url="https://source.com",
    )
    inserted = temp_db.insert_lead(lead)

    inserted.creator_name = "Updated Name"
    inserted.score = 88.0
    inserted.priority = "A"
    inserted.qualification_status = "qualified"

    temp_db.update_lead(inserted)

    fetched = temp_db.get_lead_by_id(inserted.id)
    assert fetched.creator_name == "Updated Name"
    assert fetched.score == 88.0
    assert fetched.priority == "A"
    assert fetched.qualification_status == "qualified"


def test_verification_audit_log(temp_db):
    lead = Lead(
        creator_name="Audited Creator",
        creator_type="podcaster",
        country="United Kingdom",
        platform="youtube",
        platform_id="UC_AUDIT",
        official_profile_url="https://youtube.com/@audit",
        candidate_source_url="https://src.com",
    )
    inserted = temp_db.insert_lead(lead)

    vlog = VerificationLog(
        lead_id=inserted.id,
        platform="youtube",
        platform_id="UC_AUDIT",
        action="qualification_evaluation",
        status_before="discovered",
        status_after="qualified",
        disqualification_reasons=[],
        score=85.0,
        priority="A",
        run_id="run_test_1",
        details={"checked_by": "unit_test"},
    )
    log_id = temp_db.log_verification(vlog)
    assert log_id > 0

    logs = temp_db.get_verification_logs(platform_id="UC_AUDIT")
    assert len(logs) == 1
    assert logs[0].status_after == "qualified"
    assert logs[0].score == 85.0
    assert logs[0].run_id == "run_test_1"


def test_database_metrics(temp_db):
    # Insert 1 qualified, 1 discovered, 1 disqualified
    l1 = Lead(
        creator_name="Q1",
        creator_type="podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_Q1",
        official_profile_url="https://youtube.com/@q1",
        candidate_source_url="https://src.com",
        qualification_status="qualified",
        priority="A",
    )
    l2 = Lead(
        creator_name="D1",
        creator_type="coach_creator",
        country="United States",
        platform="youtube",
        platform_id="UC_D1",
        official_profile_url="https://youtube.com/@d1",
        candidate_source_url="https://src.com",
        qualification_status="discovered",
    )
    l3 = Lead(
        creator_name="DQ1",
        creator_type="agency",
        country="Germany",
        platform="youtube",
        platform_id="UC_DQ1",
        official_profile_url="https://youtube.com/@dq1",
        candidate_source_url="https://src.com",
        qualification_status="disqualified",
    )

    temp_db.insert_lead(l1)
    temp_db.insert_lead(l2)
    temp_db.insert_lead(l3)

    metrics = temp_db.get_metrics()
    assert metrics["total_candidates"] == 3
    assert metrics["qualified"] == 1
    assert metrics["discovered"] == 1
    assert metrics["disqualified"] == 1
    assert metrics["priority_breakdown"].get("A") == 1
