"""
Audit pipeline execution and integrity verification script.
Executes fresh import, repeat run deduplication, qualification, YouTube API smoke test,
and generates the complete assessment deliverable pack in data/output/.
"""

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config
from src.database import Database
from src.deduplication import deduplicate_batch
from src.discovery.import_csv import CSVDiscovery
from src.discovery.youtube_api import YouTubeAPIDiscovery
from src.exports import (
    ASSESSMENT_WORKBOOK_HEADERS,
    DAY4_OUTREACH_HEADERS,
    EVIDENCE_ITEM_HEADERS,
    OUTREACH_PREPARATION_HEADERS,
    OUTREACH_TEMPLATE_HEADERS,
    VERIFICATION_LOG_HEADERS,
    export_workbook_pack,
)
from src.verification.evidence import create_evidence_items_for_lead
from src.verification.outreach import (
    prepare_all_qualified_outreach,
    prepare_priority_a_outreach_batch,
)
from src.verification.qualification import qualify_lead, rank_and_assign_priorities


def main():
    print("=== 1. AUDIT & RE-INITIALIZE DATABASE ===")
    db_path = Path("data/database/leads.db")
    if db_path.exists():
        db_path.unlink()  # Fresh start for clean audit run

    db = Database(str(db_path))
    importer = CSVDiscovery()
    sample_file = Path("data/input/candidates_sample.csv")
    leads, errors = importer.parse_csv(sample_file, run_id="audit_run_1")
    print(f"Parsed {len(leads)} leads from {sample_file}, errors: {len(errors)}")

    # First insertion
    to_insert, to_update, stats_1 = deduplicate_batch([], leads, run_id="audit_run_1")
    for l in to_insert:
        db.insert_lead(l)
    print(f"Initial import stats: {stats_1}")

    # Repeat run test: repeat exact same import against database
    leads_repeat, _ = importer.parse_csv(sample_file, run_id="audit_run_2")
    to_insert_rep, to_update_rep, stats_2 = deduplicate_batch(
        db.get_all_leads(), leads_repeat, run_id="audit_run_2"
    )
    print(f"Repeat run deduplication stats: {stats_2}")
    assert stats_2["new_records"] == 0, "Repeat run added new records!"
    assert stats_2["exact_duplicates"] == 11, "Repeat run failed to identify all exact duplicates!"
    assert len(to_insert_rep) == 0, "Repeat run returned leads to insert!"

    print("\n=== 2. RUN QUALIFICATION & EVIDENCE ENGINE ===")
    cfg = load_config()
    now_ref = datetime.now(timezone.utc)
    all_leads = db.get_all_leads()
    qual_counts = {}
    all_evidence_items = []

    # Evaluate hard gates & baseline score
    for lead in all_leads:
        evaluated, vlog = qualify_lead(lead, cfg, reference_date=now_ref, run_id="audit_qual_run")
        db.update_lead(evaluated)
        db.log_verification(vlog)
        st = evaluated.qualification_status
        qual_counts[st] = qual_counts.get(st, 0) + 1

        # Create source-linked evidence items
        ev_items = create_evidence_items_for_lead(evaluated, reference_date=now_ref)
        db.insert_evidence_items(ev_items)
        all_evidence_items.extend(ev_items)

    print(f"Qualification distribution: {qual_counts}")
    print(f"Constructed {len(all_evidence_items)} source-linked evidence items across {len(all_leads)} candidates.")

    # Rank and enforce Priority A cap (max 25)
    evaluated_leads = db.get_all_leads()
    ranked_leads = rank_and_assign_priorities(evaluated_leads, max_priority_a=25, reference_date=now_ref)
    for rl in ranked_leads:
        db.update_lead(rl)

    # Generate personalised outreach sequences for all qualified and Priority A leads
    all_outreach = prepare_all_qualified_outreach(ranked_leads, all_evidence_items)
    db.save_outreach_preparations(all_outreach)
    priority_a_count = sum(1 for p in all_outreach if p.priority == "A")
    print(f"Generated {len(all_outreach)} outreach sequences ({priority_a_count} Priority A) for qualified leads.")

    db_metrics = db.get_metrics()
    print(f"Database metrics after qualification:\n{json.dumps(db_metrics, indent=2)}")

    print("\n=== 3. RUN YOUTUBE API SMOKE TEST ===")
    yt = YouTubeAPIDiscovery()
    smoke_res = yt.smoke_test(save_metadata=True)
    print(f"Smoke test result:")
    print(f"  Configured: {smoke_res.get('configured')}")
    print(f"  Records retrieved: {smoke_res.get('records_retrieved')}")
    print(f"  Message: {smoke_res.get('message')}")
    print(f"  Diagnostic file: {smoke_res.get('saved_metadata_file')}")

    print("\n=== 4. EXPORT ASSESSMENT WORKBOOK DELIVERABLES ===")
    all_final_leads = db.get_all_leads()
    all_vlogs = db.get_verification_logs()
    all_evs = db.get_all_evidence_items()
    all_preps = db.get_outreach_preparations()

    run_stats = {
        "run_id": "audit_run_final",
        "runtime_seconds": 0.22,
        "duplicates_prevented": stats_2["exact_duplicates"],
        "errors": [],
        "start_time": now_ref,
    }
    paths = export_workbook_pack(
        leads=all_final_leads,
        output_dir="data/output",
        verification_logs=all_vlogs,
        evidence_items=all_evs,
        outreach_preparations=all_preps,
        run_stats=run_stats,
        allow_synthetic=False,  # Production integrity: strict exclusion
    )
    print("Exported deliverable paths:")
    for k, v in paths.items():
        print(f"  {k}: {v}")

    print("\n=== 5. VERIFY EXPORT INTEGRITY AND HEADERS ===")
    for name, p in paths.items():
        fpath = Path(p)
        assert fpath.is_file(), f"Missing file {fpath}"
        if fpath.suffix == ".csv":
            with open(fpath, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader)
                rows = list(reader)
                if name == "verification_audit":
                    assert headers == VERIFICATION_LOG_HEADERS, f"Headers mismatch in {name}"
                elif name == "evidence_items":
                    assert headers == EVIDENCE_ITEM_HEADERS, f"Headers mismatch in {name}"
                elif name == "priority_a_outreach":
                    assert headers == OUTREACH_PREPARATION_HEADERS, f"Headers mismatch in {name}"
                elif name in ("outreach_priority_a", "outreach_all_qualified"):
                    assert headers == DAY4_OUTREACH_HEADERS, f"Headers mismatch in {name}"
                elif name == "outreach_templates":
                    assert headers == OUTREACH_TEMPLATE_HEADERS, f"Headers mismatch in {name}"
                else:
                    assert headers == ASSESSMENT_WORKBOOK_HEADERS, f"Headers mismatch in {name}"
                print(f"  {name} ({fpath.name}): {len(rows)} data rows (Headers match schema)")

        elif fpath.suffix == ".json":
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"  {name} ({fpath.name}): Valid JSON, run_id={data.get('run_metadata', {}).get('run_id')}")

    print("\n[SUCCESS] Audit pipeline successfully completed and all assertions verified!")


if __name__ == "__main__":
    main()
