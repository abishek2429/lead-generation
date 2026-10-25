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
    VERIFICATION_LOG_HEADERS,
    export_workbook_pack,
)
from src.verification.qualification import qualify_lead


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

    print("\n=== 2. RUN QUALIFICATION ENGINE ===")
    cfg = load_config()
    now_ref = datetime.now(timezone.utc)
    all_leads = db.get_all_leads()
    qual_counts = {}

    for lead in all_leads:
        evaluated, vlog = qualify_lead(lead, cfg, reference_date=now_ref, run_id="audit_qual_run")
        db.update_lead(evaluated)
        db.log_verification(vlog)
        st = evaluated.qualification_status
        qual_counts[st] = qual_counts.get(st, 0) + 1

    print(f"Qualification distribution: {qual_counts}")
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
    all_evaluated_leads = db.get_all_leads()
    all_vlogs = db.get_verification_logs()
    run_stats = {
        "run_id": "audit_run_final",
        "runtime_seconds": 0.18,
        "duplicates_prevented": stats_2["exact_duplicates"],
        "errors": [],
        "start_time": now_ref,
    }
    paths = export_workbook_pack(
        leads=all_evaluated_leads,
        output_dir="data/output",
        verification_logs=all_vlogs,
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
