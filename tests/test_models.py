"""
Unit tests for Lead and VerificationLog Pydantic data models.
Ensures missing evidence is strictly represented as None/empty, never fabricated.
"""

import json
import pytest
from src.models import Lead, QualificationStatus, VerificationLog


def test_lead_initialization_defaults():
    lead = Lead(
        creator_name="Acme Creator",
        creator_type="podcaster",
        country="United States",
        language="English",
        platform="youtube",
        platform_id="UC123456",
        official_profile_url="https://youtube.com/@acmecreator",
        candidate_source_url="https://youtube.com/search",
    )
    assert lead.qualification_status == QualificationStatus.DISCOVERED.value
    assert lead.score == 0.0
    assert lead.priority is None
    assert lead.recent_content_urls == []
    assert lead.recent_content_dates == []
    assert lead.commercial_evidence_url is None
    assert lead.workflow_need_evidence_url is None
    assert lead.business_contact_value is None
    assert lead.disqualification_reasons == []
    assert lead.first_discovered_at is not None


def test_lead_empty_strings_convert_to_none():
    lead = Lead(
        creator_name="Test Creator",
        creator_type="educator_creator",
        country="",
        commercial_evidence_url="   ",
        workflow_need_evidence_url="None",
        business_contact_value="null",
        platform="youtube",
        platform_id="UC999",
        official_profile_url="https://youtube.com/@test",
        candidate_source_url="https://google.com",
    )
    assert lead.country is None
    assert lead.commercial_evidence_url is None
    assert lead.workflow_need_evidence_url is None
    assert lead.business_contact_value is None


def test_lead_list_field_parsing():
    lead = Lead(
        creator_name="List Creator",
        creator_type="podcaster",
        platform="youtube",
        platform_id="UC888",
        official_profile_url="https://youtube.com/@list",
        candidate_source_url="https://test.com",
        recent_content_urls='["https://youtube.com/watch?v=1", "https://youtube.com/watch?v=2"]',
        recent_content_dates="2026-10-01, 2026-10-15",
        disqualification_reasons="reason 1, reason 2",
    )
    assert lead.recent_content_urls == [
        "https://youtube.com/watch?v=1",
        "https://youtube.com/watch?v=2",
    ]
    assert lead.recent_content_dates == ["2026-10-01", "2026-10-15"]
    assert lead.disqualification_reasons == ["reason 1", "reason 2"]


def test_db_serialization_roundtrip():
    original = Lead(
        creator_name="Roundtrip Creator",
        creator_type="video_podcaster",
        country="United Kingdom",
        platform="youtube",
        platform_id="UC_ROUNDTRIP",
        official_profile_url="https://youtube.com/@roundtrip",
        candidate_source_url="https://source.com",
        recent_content_urls=["https://youtube.com/watch?v=abc"],
        recent_content_dates=["2026-10-20"],
        commercial_evidence_url="https://roundtrip.com/course",
        workflow_need_evidence_url="https://roundtrip.com/podcast",
        business_contact_type="email",
        business_contact_value="host@roundtrip.com",
        business_contact_source_url="https://roundtrip.com/contact",
        business_contact_last_active="2026-10-18",
        evidence_checked_at="2026-10-24T12:00:00Z",
        qualification_status="qualified",
        disqualification_reasons=[],
        score=92.5,
        priority="A",
    )

    db_dict = original.to_db_dict()
    assert isinstance(db_dict["recent_content_urls"], str)
    assert isinstance(db_dict["recent_content_dates"], str)
    assert isinstance(db_dict["disqualification_reasons"], str)

    restored = Lead.from_db_row(db_dict)
    assert restored.creator_name == original.creator_name
    assert restored.recent_content_urls == original.recent_content_urls
    assert restored.recent_content_dates == original.recent_content_dates
    assert restored.score == original.score
    assert restored.priority == original.priority
    assert restored.qualification_status == "qualified"
