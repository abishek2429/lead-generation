"""
End-to-End integration test covering the complete Day 2 acceptance lifecycle:
1. Automatic database initialization
2. CSV Candidate import (candidates start as 'discovered')
3. Deterministic deduplication & merge
4. Qualification hard gates evaluation
5. Deliverables export distinguishing candidates from qualified leads
"""

import csv
import json
import tempfile
from pathlib import Path
import pytest
from src.config import load_config
from src.database import Database
from src.deduplication import deduplicate_batch
from src.discovery.import_csv import CSVDiscovery
from src.exports import ASSESSMENT_WORKBOOK_HEADERS, export_workbook_pack
from src.models import QualificationStatus
from src.verification.qualification import qualify_lead


def test_full_day2_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "leads_test.db"
        output_dir = tmp_path / "output"

        # 1. Database initialises automatically
        db = Database(str(db_path))
        assert db_path.is_file()
        metrics = db.get_metrics()
        assert metrics["total_candidates"] == 0

        # 2. CSV Import works from candidates_sample.csv
        sample_csv = Path("data/input/candidates_sample.csv")
        assert sample_csv.is_file()

        importer = CSVDiscovery()
        leads, errors = importer.parse_csv(sample_csv, run_id="run_e2e_1")
        assert len(errors) == 0
        assert len(leads) >= 10

        # Candidates start in 'discovered' status
        for l in leads:
            assert l.qualification_status == QualificationStatus.DISCOVERED.value

        # 3. Insert discovered leads into DB
        for l in leads:
            db.insert_lead(l)

        metrics_after_import = db.get_metrics()
        assert metrics_after_import["total_candidates"] == len(leads)
        assert metrics_after_import["discovered"] == len(leads)
        assert metrics_after_import["qualified"] == 0

        # 4. Duplicate records are rejected or merged deterministically
        existing_leads = db.get_all_leads()
        to_insert, to_update, stats = deduplicate_batch(
            existing_leads=existing_leads,
            incoming_candidates=leads,  # re-import exact same batch
            run_id="run_e2e_2",
        )
        assert stats["new_records"] == 0
        assert stats["exact_duplicates"] == len(leads)
        assert len(to_insert) == 0

        # 5. Qualification logic execution
        cfg = load_config()
        qualified_count = 0
        needs_review_count = 0
        disqualified_count = 0

        for lead in db.get_all_leads():
            evaluated, vlog = qualify_lead(lead, cfg, run_id="run_e2e_qual")
            db.update_lead(evaluated)
            db.log_verification(vlog)
            if evaluated.qualification_status == QualificationStatus.QUALIFIED.value:
                qualified_count += 1
            elif evaluated.qualification_status == QualificationStatus.NEEDS_REVIEW.value:
                needs_review_count += 1
            else:
                disqualified_count += 1

        assert qualified_count > 0
        assert needs_review_count > 0
        assert disqualified_count > 0

        post_qual_metrics = db.get_metrics()
        assert post_qual_metrics["qualified"] == qualified_count
        assert post_qual_metrics["needs_review"] == needs_review_count
        assert post_qual_metrics["disqualified"] == disqualified_count
        assert post_qual_metrics["discovered"] == 0

        # 6. Exports distinguish candidates from qualified leads and isolate synthetic fixtures
        leads_to_export = db.get_all_leads()
        pack = export_workbook_pack(leads_to_export, output_dir=str(output_dir))

        # Check default qualified leads export (CRITICAL: synthetic fixtures strictly excluded)
        with open(pack["qualified_leads"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            # All sample candidates are synthetic fixtures, so production export contains zero real leads
            assert len(reader) == 0

        # Check export with allow_synthetic=True for testing/validation
        pack_syn = export_workbook_pack(leads_to_export, output_dir=str(output_dir / "syn"), allow_synthetic=True)
        with open(pack_syn["qualified_leads"], "r", encoding="utf-8") as f:
            reader_syn = list(csv.DictReader(f))
            assert len(reader_syn) == qualified_count
            for row in reader_syn:
                assert row["qualification_status"] == "qualified"
                assert row["score"] != ""
                assert float(row["score"]) > 0

        # Check needs_review export
        with open(pack["needs_review"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == needs_review_count
            for row in reader:
                assert row["qualification_status"] == "needs_review"

        # Check all candidates export
        with open(pack["all_candidates"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == len(leads_to_export)

        # Check disqualification audit export
        with open(pack["disqualification_audit"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == disqualified_count
            for row in reader:
                assert row["qualification_status"] == "disqualified"
                assert len(row["disqualification_reasons"]) > 2  # not empty json

        # Check verification audit log and run summary exist
        assert Path(pack["verification_audit"]).is_file()
        assert Path(pack["run_summary"]).is_file()

        # Check exact workbook headers
        with open(pack["qualified_leads"], "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ASSESSMENT_WORKBOOK_HEADERS
