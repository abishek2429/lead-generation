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


def test_end_to_end_10_step_qa_lifecycle():
    """
    Rigorously test the complete 10-step lifecycle requested by Senior QA:
    1. Import or discover candidates from clearly labelled synthetic fixtures.
    2. Persist them in SQLite.
    3. Deduplicate records.
    4. Evaluate qualification gates.
    5. Store evidence and verification decisions.
    6. Score qualified leads transparently.
    7. Select eligible Priority A leads (capped at 25, no forcing).
    8. Generate outreach drafts (3 touches, grounded copy, honest identity).
    9. Export candidates, qualified leads, audit data and outreach files.
       Verify synthetic isolation: synthetic leads NEVER appear in real qualified exports!
    10. Rerun the same input and verify 100% idempotency.
    """
    from datetime import datetime, timezone
    from src.exports import (
        DAY4_OUTREACH_HEADERS,
        EVIDENCE_ITEM_HEADERS,
        OUTREACH_PREPARATION_HEADERS,
        OUTREACH_TEMPLATE_HEADERS,
        VERIFICATION_LOG_HEADERS,
    )
    from src.verification.evidence import create_evidence_items_for_lead
    from src.verification.outreach import prepare_all_qualified_outreach
    from src.verification.qualification import rank_and_assign_priorities
    from src.verification.templates import SENDER_IDENTITY

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "lifecycle_leads.db"
        output_dir = tmp_path / "output"
        sample_csv = Path("data/input/candidates_sample.csv")
        assert sample_csv.is_file()

        # Step 1: Import or discover candidates from synthetic fixtures
        importer = CSVDiscovery()
        leads, parse_errors = importer.parse_csv(sample_csv, run_id="qa_step1")
        assert len(parse_errors) == 0
        assert len(leads) == 11
        for lead in leads:
            assert lead.is_synthetic is True, f"Lead {lead.creator_name} is not flagged synthetic!"
            assert lead.qualification_status == QualificationStatus.DISCOVERED.value

        # Step 2: Persist them in SQLite
        db = Database(str(db_path))
        to_insert_init, _, stats_init = deduplicate_batch([], leads, run_id="qa_step2")
        for l in to_insert_init:
            db.insert_lead(l)
        
        all_initial = db.get_all_leads()
        assert len(all_initial) == 11
        assert db.get_metrics()["discovered"] == 11
        assert db.get_metrics()["synthetic_candidates"] == 11
        assert db.get_metrics()["real_candidates"] == 0

        # Step 3: Deduplicate records
        to_insert_dedup, to_update_dedup, stats_dedup = deduplicate_batch(
            existing_leads=all_initial,
            incoming_candidates=leads,
            run_id="qa_step3",
        )
        assert stats_dedup["new_records"] == 0
        assert stats_dedup["exact_duplicates"] == 11
        assert len(to_insert_dedup) == 0

        # Step 4: Evaluate qualification gates
        cfg = load_config()
        now_ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        qual_dist = {}
        for lead in all_initial:
            eval_lead, vlog = qualify_lead(lead, cfg, reference_date=now_ref, run_id="qa_step4")
            db.update_lead(eval_lead)
            db.log_verification(vlog)
            st = eval_lead.qualification_status
            qual_dist[st] = qual_dist.get(st, 0) + 1

        assert qual_dist[QualificationStatus.QUALIFIED.value] == 7
        assert qual_dist[QualificationStatus.DISQUALIFIED.value] == 3
        assert qual_dist[QualificationStatus.NEEDS_REVIEW.value] == 1

        # Step 5: Store evidence and verification decisions
        all_eval_leads = db.get_all_leads()
        all_evidence_items = []
        for lead in all_eval_leads:
            ev_items = create_evidence_items_for_lead(lead, reference_date=now_ref)
            assert len(ev_items) == 7, "Each lead must produce exactly 7 source-linked evidence items"
            db.insert_evidence_items(ev_items)
            all_evidence_items.extend(ev_items)

        db_evidence = db.get_all_evidence_items()
        assert len(db_evidence) == 77
        vlogs = db.get_verification_logs()
        assert len(vlogs) == 11

        # Step 6: Score qualified leads
        for q_lead in db.get_all_leads(status=QualificationStatus.QUALIFIED.value):
            assert q_lead.score > 0.0
            assert "workflow_need" in q_lead.score_breakdown
            assert "segment_fit" in q_lead.score_breakdown
            assert "commercial_intent" in q_lead.score_breakdown
            assert "publishing_consistency" in q_lead.score_breakdown
            assert "contact_channel_quality" in q_lead.score_breakdown

        for non_q in db.get_all_leads():
            if non_q.qualification_status != QualificationStatus.QUALIFIED.value:
                assert non_q.score == 0.0

        # Step 7: Select eligible Priority A leads
        ranked = rank_and_assign_priorities(all_eval_leads, max_priority_a=25, reference_date=now_ref)
        for rl in ranked:
            db.update_lead(rl)

        pri_a_leads = [l for l in db.get_all_leads() if (l.priority or "").upper() == "A"]
        assert len(pri_a_leads) == 7
        assert len(pri_a_leads) <= 25  # Capped at 25

        # Step 8: Generate outreach drafts
        outreach_preps = prepare_all_qualified_outreach(ranked, db_evidence)
        assert len(outreach_preps) == 7
        for prep in outreach_preps:
            assert prep.is_synthetic is True
            assert prep.sender_identity == SENDER_IDENTITY
            assert "http" in prep.specific_content_source_url
            assert len(prep.proposed_first_message) > 50
            assert len(prep.follow_up_1) > 50
            assert len(prep.follow_up_2) > 50
            assert "opt-out" in prep.opt_out_language.lower()
        db.save_outreach_preparations(outreach_preps)

        # Step 9: Export candidates, qualified leads, audit data and outreach files
        pack = export_workbook_pack(
            leads=db.get_all_leads(),
            output_dir=str(output_dir),
            verification_logs=db.get_verification_logs(),
            evidence_items=db.get_all_evidence_items(),
            outreach_preparations=db.get_outreach_preparations(),
            allow_synthetic=False,  # Strict production isolation
        )

        # Integrity check: synthetic fixtures must NEVER appear in real-lead exports
        with open(pack["qualified_leads"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 0, "Synthetic fixture leaked into production qualified_leads.csv!"

        with open(pack["priority_a_outreach"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 0, "Synthetic fixture leaked into production priority_a_outreach.csv!"

        with open(pack["outreach_priority_a"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 0, "Synthetic fixture leaked into production outreach_priority_a.csv!"

        with open(pack["outreach_all_qualified"], "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 0, "Synthetic fixture leaked into production outreach_all_qualified.csv!"

        # Audit and candidate files must contain records
        with open(pack["all_candidates"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 11

        with open(pack["needs_review"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 1

        with open(pack["disqualification_audit"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 3

        with open(pack["verification_audit"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 11

        with open(pack["evidence_items"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 77

        with open(pack["outreach_templates"], "r", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 45

        # Step 10: Rerun the same input and verify idempotency
        leads_rerun, errors_rerun = importer.parse_csv(sample_csv, run_id="qa_step10")
        assert len(errors_rerun) == 0
        to_insert_rep, to_update_rep, stats_rep = deduplicate_batch(
            existing_leads=db.get_all_leads(),
            incoming_candidates=leads_rerun,
            run_id="qa_step10",
        )
        assert stats_rep["new_records"] == 0, "Idempotency failure: new records inserted on rerun!"
        assert stats_rep["exact_duplicates"] == 11, "Idempotency failure: failed to recognize exact duplicates!"
        assert len(to_insert_rep) == 0, "Idempotency failure: to_insert is non-empty!"
        assert len(db.get_all_leads()) == 11, "Idempotency failure: database row count changed on rerun!"

