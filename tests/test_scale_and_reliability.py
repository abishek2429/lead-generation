"""
Scale, performance, and reliability regression tests.
Verifies system reliability under stress:
1. Repeat import idempotency (importing same dataset twice).
2. Datasets with overlapping IDs (deterministic merge without duplicate records).
3. Interrupted run resumption (partial commit followed by full re-run).
4. Simulated API timeouts and quota errors (mocked network failures).
5. Transaction rollback and recovery on database error.
6. Evidence and qualification status consistency after refresh.
7. Zero duplicate records and zero duplicate outreach drafts.
8. Production export isolation (synthetic fixtures never leak into qualified leads).
"""

import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.config import load_config
from src.database import Database
from src.deduplication import canonicalize_url, deduplicate_batch
from src.discovery.import_csv import CSVDiscovery
from src.discovery.youtube_api import YouTubeAPIDiscovery
from src.exports import export_leads_csv, export_workbook_pack
from src.models import (
    CampaignOutreachRecord,
    EvidenceItem,
    EvidenceType,
    Lead,
    OutreachPreparation,
    QualificationStatus,
    VerificationLog,
    VerificationStatus,
)
from src.verification.evidence import create_evidence_items_for_lead, safe_http_head_or_get
from src.verification.outreach import prepare_all_qualified_outreach
from src.verification.qualification import qualify_lead, rank_and_assign_priorities


@pytest.fixture
def temp_db(tmp_path):
    """Provide an isolated, empty SQLite test database."""
    db_file = tmp_path / "scale_test.db"
    return Database(str(db_file))


@pytest.fixture
def benchmark_100_leads():
    """Load the 100-record synthetic fixture."""
    fixture_path = Path("data/benchmarks/benchmark_100.csv")
    importer = CSVDiscovery()
    leads, errors = importer.parse_csv(fixture_path, run_id="bench_100_fixture")
    assert len(leads) == 100, f"Expected 100 benchmark leads, got {len(leads)}"
    return leads


class TestScaleAndReliability:

    def test_import_same_dataset_twice_prevents_all_duplicates(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 1:
        Importing the exact same dataset twice must detect 100% duplicates on the second run,
        insert 0 new records, and keep database record count identical.
        """
        # First import
        to_insert, to_update, stats_1 = deduplicate_batch([], benchmark_100_leads, run_id="run_1")
        temp_db.insert_leads_batch(to_insert)

        initial_count = len(temp_db.get_all_leads())
        assert initial_count > 0

        # Second import of exact same records
        existing_leads = temp_db.get_all_leads()
        to_insert_2, to_update_2, stats_2 = deduplicate_batch(
            existing_leads, benchmark_100_leads, run_id="run_2"
        )

        assert len(to_insert_2) == 0, "Second import must produce 0 inserts"
        assert stats_2["new_records"] == 0
        duplicates_prevented = len(benchmark_100_leads) - stats_2["new_records"]
        assert duplicates_prevented == len(benchmark_100_leads)

        # Database record count remains unchanged
        final_count = len(temp_db.get_all_leads())
        assert final_count == initial_count, "Database record count changed on duplicate import"

    def test_import_datasets_with_overlapping_ids(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 2:
        Importing datasets with overlapping IDs must deterministically merge
        shared IDs without creating duplicate records.
        """
        # Subset A: items 0..59 (60 records)
        subset_a = benchmark_100_leads[:60]
        # Subset B: items 30..89 (60 records, 30 overlapping with subset A, 30 new)
        subset_b = benchmark_100_leads[30:90]

        # Import subset A
        to_insert_a, _, _ = deduplicate_batch([], subset_a, run_id="batch_a")
        temp_db.insert_leads_batch(to_insert_a)
        count_a = len(temp_db.get_all_leads())
        assert count_a == len(to_insert_a)

        # Import subset B
        existing_leads = temp_db.get_all_leads()
        to_insert_b, to_update_b, stats_b = deduplicate_batch(
            existing_leads, subset_b, run_id="batch_b"
        )
        temp_db.insert_leads_batch(to_insert_b)
        temp_db.update_leads_batch(to_update_b)

        # Total unique leads should be exactly union of 0..89 (90 records minus any internal duplicates)
        final_leads = temp_db.get_all_leads()
        unique_platform_keys = {f"{l.platform}:{l.platform_id.lower()}" for l in final_leads}
        assert len(final_leads) == len(unique_platform_keys), "Database contains duplicate platform keys"

    def test_resume_after_interrupted_run(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 3:
        Simulate an interrupted run where half the batch was persisted before a failure.
        Resuming with the full batch must complete without duplicating existing leads.
        """
        # Step 1: Process and persist only first 40 records (interrupted state)
        partial_leads = benchmark_100_leads[:40]
        to_insert_partial, _, _ = deduplicate_batch([], partial_leads, run_id="partial_run")
        temp_db.insert_leads_batch(to_insert_partial)
        partial_count = len(temp_db.get_all_leads())
        assert partial_count == len(to_insert_partial)

        # Step 2: Resume with the FULL batch of 100 records
        existing_leads = temp_db.get_all_leads()
        to_insert_resumed, to_update_resumed, stats_resumed = deduplicate_batch(
            existing_leads, benchmark_100_leads, run_id="resumed_run"
        )

        temp_db.insert_leads_batch(to_insert_resumed)
        temp_db.update_leads_batch(to_update_resumed)

        final_leads = temp_db.get_all_leads()
        platform_keys = [f"{l.platform}:{l.platform_id.lower()}" for l in final_leads]
        assert len(platform_keys) == len(set(platform_keys)), "Duplicate platform keys after resume"

    def test_simulated_api_timeouts_and_quota_errors(self, temp_db):
        """
        Reliability Check 4:
        Simulate HTTP connection timeouts and 403 API quota errors.
        System must handle errors gracefully without unhandled exceptions.
        """
        # 1. Simulate network timeout in safe_http_head_or_get
        with patch("requests.head", side_effect=requests.exceptions.Timeout("Connection timed out")):
            success, status, msg = safe_http_head_or_get("https://example.com/test", timeout=1)
            assert success is False
            assert "timed out" in msg.lower()

        # 2. Simulate 403 Quota Exceeded in safe_http_head_or_get
        mock_resp_403 = MagicMock()
        mock_resp_403.status_code = 403
        with patch("requests.head", return_value=mock_resp_403):
            success, status, msg = safe_http_head_or_get("https://example.com/test")
            assert success is False
            assert status == 403
            assert "403" in msg

        # 3. Simulate YouTube API 403 Quota Error
        yt = YouTubeAPIDiscovery()
        mock_resp_yt_quota = MagicMock()
        mock_resp_yt_quota.status_code = 403
        mock_resp_yt_quota.json.return_value = {
            "error": {"code": 403, "message": "The request cannot be completed because you have exceeded your quota."}
        }
        with patch("requests.get", return_value=mock_resp_yt_quota):
            res = yt.search_channels("podcasters", max_results=5)
            # Must return empty list rather than crashing
            assert res == []

    def test_transaction_rollback_and_recovery(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 5:
        Verify transaction rollback on database error and recovery of subsequent operations.
        """
        # Insert initial clean leads
        initial_lead = benchmark_100_leads[0].model_copy()
        temp_db.insert_lead(initial_lead)
        initial_db_count = len(temp_db.get_all_leads())
        assert initial_db_count == 1

        # Attempt an operation that triggers a database integrity / SQL syntax error
        with pytest.raises(Exception):
            with temp_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO leads (creator_name, platform, platform_id, official_profile_url, candidate_source_url, qualification_status) VALUES ('fail_lead', 'youtube', 'fail_yt', 'http://fail', 'http://fail', 'discovered')")
                # Intentionally trigger an error halfway through transaction
                cursor.execute("INSERT INTO nonexistent_table (col) VALUES (1)")

        # Verify rollback: 'fail_lead' was NOT committed to the database
        recovered_leads = temp_db.get_all_leads()
        assert len(recovered_leads) == initial_db_count
        assert not any(l.platform_id == "fail_yt" for l in recovered_leads)

        # Subsequent transaction succeeds normally
        clean_lead = benchmark_100_leads[1].model_copy()
        temp_db.insert_lead(clean_lead)
        assert len(temp_db.get_all_leads()) == 2

    def test_evidence_and_qualification_statuses_consistent_after_refresh(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 6:
        Confirm evidence generation and qualification evaluation are strictly deterministic
        and produce identical statuses when refreshed.
        """
        cfg = load_config()
        ref_date = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # Deduplicate to get distinct unique leads
        unique_leads_map = {l.platform_id: l.model_copy() for l in benchmark_100_leads}
        leads = list(unique_leads_map.values())[:30]
        temp_db.insert_leads_batch(leads)

        # First qualification pass
        first_pass_statuses = {}
        for lead in leads:
            qual_lead, _ = qualify_lead(lead, cfg, reference_date=ref_date, run_id="pass_1")
            first_pass_statuses[qual_lead.platform_id] = (
                qual_lead.qualification_status,
                qual_lead.disqualification_reasons,
                qual_lead.score,
            )
            temp_db.update_lead(qual_lead)

        # Second refresh pass on the same leads
        persisted_leads = temp_db.get_all_leads()
        for lead in persisted_leads:
            refreshed_lead, _ = qualify_lead(lead, cfg, reference_date=ref_date, run_id="pass_2")
            expected_status, expected_reasons, expected_score = first_pass_statuses[refreshed_lead.platform_id]

            assert refreshed_lead.qualification_status == expected_status, (
                f"Status mismatch for {refreshed_lead.platform_id} after refresh: "
                f"{refreshed_lead.qualification_status} != {expected_status}"
            )
            assert refreshed_lead.disqualification_reasons == expected_reasons
            assert refreshed_lead.score == expected_score

    def test_no_duplicate_outreach_drafts_created(self, temp_db, benchmark_100_leads):
        """
        Reliability Check 7:
        Confirm no duplicate outreach drafts or preparations are created across repeated runs.
        """
        cfg = load_config()
        ref_date = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # Deduplicate to get distinct unique leads
        unique_leads_map = {l.platform_id: l.model_copy() for l in benchmark_100_leads}
        leads = list(unique_leads_map.values())[:50]
        temp_db.insert_leads_batch(leads)

        # Qualify and rank
        qual_leads = []
        all_ev = []
        for lead in leads:
            ql, _ = qualify_lead(lead, cfg, reference_date=ref_date)
            qual_leads.append(ql)
            evs = create_evidence_items_for_lead(ql, reference_date=ref_date)
            all_ev.extend(evs)

        ranked = rank_and_assign_priorities(qual_leads, max_priority_a=10, reference_date=ref_date)
        temp_db.update_leads_batch(ranked)

        # First outreach generation
        preps_1 = prepare_all_qualified_outreach(ranked, all_ev)
        temp_db.save_outreach_preparations(preps_1)
        count_preps_1 = len(temp_db.get_outreach_preparations())

        # Second outreach generation (exact repeat)
        preps_2 = prepare_all_qualified_outreach(ranked, all_ev)
        temp_db.save_outreach_preparations(preps_2)
        count_preps_2 = len(temp_db.get_outreach_preparations())

        assert count_preps_2 == count_preps_1, "Repeated outreach save created duplicate records"

        # Unique platform_id check
        all_preps = temp_db.get_outreach_preparations()
        platform_ids = [p.platform_id for p in all_preps]
        assert len(platform_ids) == len(set(platform_ids)), "Duplicate platform_id in outreach preparations"

    def test_synthetic_benchmarks_never_leak_into_production_qualified_exports(self, temp_db, benchmark_100_leads, tmp_path):
        """
        Reliability Check 8:
        Production exports with allow_synthetic=False must strictly exclude all synthetic benchmark records.
        """
        cfg = load_config()
        ref_date = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        qualified_synthetic = []
        for lead in benchmark_100_leads:
            ql, _ = qualify_lead(lead, cfg, reference_date=ref_date)
            qualified_synthetic.append(ql)

        out_dir = tmp_path / "prod_export"
        paths = export_workbook_pack(
            leads=qualified_synthetic,
            output_dir=str(out_dir),
            allow_synthetic=False,  # Strict production mode
        )

        # Read qualified_leads.csv
        q_path = Path(paths["qualified_leads"])
        with open(q_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        # Only header line should be present, 0 data rows
        assert len(lines) == 1, f"Expected 0 synthetic leads in qualified export, got {len(lines) - 1} rows"
