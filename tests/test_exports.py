"""
Unit tests for Export Engine.
Ensures exported CSVs strictly match assessment workbook headers and separate candidates from qualified leads.
"""

import csv
import json
import tempfile
from pathlib import Path
import pytest
from src.exports import (
    ASSESSMENT_WORKBOOK_HEADERS,
    export_leads_csv,
    export_summary_json,
    export_workbook_pack,
)
from src.models import Lead, QualificationStatus


@pytest.fixture
def sample_lead_pool():
    return [
        Lead(
            creator_name="Qualified Star",
            creator_type="video_podcaster",
            country="United States",
            platform="youtube",
            platform_id="UC_QUAL_1",
            official_profile_url="https://youtube.com/@qual1",
            candidate_source_url="https://source.com",
            recent_content_urls=["https://youtube.com/watch?v=1"],
            recent_content_dates=["2026-10-20"],
            commercial_evidence_url="https://qual1.com/store",
            workflow_need_evidence_url="https://qual1.com/podcast",
            business_contact_type="email",
            business_contact_value="host@qual1.com",
            business_contact_source_url="https://qual1.com/contact",
            business_contact_last_active="2026-10-18",
            evidence_checked_at="2026-10-24T12:00:00Z",
            qualification_status=QualificationStatus.QUALIFIED.value,
            disqualification_reasons=[],
            score=95.0,
            priority="A",
            last_run_id="run_exp_1",
        ),
        Lead(
            creator_name="Pending Candidate",
            creator_type="podcaster",
            country="United Kingdom",
            platform="youtube",
            platform_id="UC_CAND_2",
            official_profile_url="https://youtube.com/@cand2",
            candidate_source_url="https://source.com",
            qualification_status=QualificationStatus.DISCOVERED.value,
        ),
        Lead(
            creator_name="Rejected Agency",
            creator_type="agency",
            country="Germany",
            platform="youtube",
            platform_id="UC_REJ_3",
            official_profile_url="https://youtube.com/@rej3",
            candidate_source_url="https://source.com",
            qualification_status=QualificationStatus.DISQUALIFIED.value,
            disqualification_reasons=["Excluded creator type 'agency'"],
        ),
    ]


def test_export_workbook_headers_match(sample_lead_pool):
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_csv = Path(tmp_dir) / "test_leads.csv"
        export_leads_csv(sample_lead_pool, str(out_csv))

        with open(out_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ASSESSMENT_WORKBOOK_HEADERS


def test_export_filters_candidates_vs_qualified(sample_lead_pool):
    with tempfile.TemporaryDirectory() as tmp_dir:
        qual_csv = Path(tmp_dir) / "qualified_only.csv"
        export_leads_csv(sample_lead_pool, str(qual_csv), filter_status="qualified")

        with open(qual_csv, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 1
            assert reader[0]["creator_name"] == "Qualified Star"
            assert reader[0]["qualification_status"] == "qualified"
            assert reader[0]["priority"] == "A"


def test_export_workbook_pack(sample_lead_pool):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pack = export_workbook_pack(sample_lead_pool, output_dir=tmp_dir)

        assert Path(pack["qualified_leads"]).is_file()
        assert Path(pack["all_candidates"]).is_file()
        assert Path(pack["disqualification_audit"]).is_file()
        assert Path(pack["summary_report"]).is_file()

        with open(pack["summary_report"], "r", encoding="utf-8") as f:
            report = json.load(f)
            assert report["summary"]["total_candidates"] == 3
            assert report["summary"]["qualified_leads"] == 1
            assert report["summary"]["discovered_pending"] == 1
            assert report["summary"]["disqualified_candidates"] == 1
