"""
Benchmark fixture generator for IncuBrix Lead Generation Engine.
Generates clearly labelled synthetic test fixtures at sizes:
- 100 records
- 1,000 records
- 5,000 records

CRITICAL POLICY REQUIREMENT:
All synthetic records are explicitly tagged with `is_synthetic = True`, prefixed with
`[SYNTHETIC-BENCHMARK]`, and use synthetic test domains. They are performance fixtures only
and must NEVER enter real creator exports or qualified-lead counts.
"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any


def generate_synthetic_dataset(
    size: int,
    duplicate_rate: float = 0.10,
    seed_offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Generate synthetic records with controlled qualification attributes:
    - ~60% fully qualified candidates
    - ~15% needs review (missing commercial or workflow evidence)
    - ~15% disqualified (agency, non-target country, or inactive content >90d)
    - duplicate_rate: fraction of rows that intentionally repeat earlier platform IDs for dedup testing
    """
    now = datetime.now(timezone.utc)
    records: List[Dict[str, Any]] = []

    # Segments matching qualification_config.json
    creator_types = [
        "podcaster",
        "video_podcaster",
        "youtube_video_first_creator",
        "coach_creator",
        "consultant_creator",
        "educator_creator",
    ]
    # Countries matching qualification_config.json
    countries = ["United States", "United Kingdom", "Canada", "Australia"]

    for idx in range(1, size + 1):
        global_idx = seed_offset + idx

        # Determine if this row is an intentional duplicate of an earlier row
        is_dup = (idx > 10) and (idx % int(1 / duplicate_rate) == 0)
        target_idx = (idx - 5) if is_dup else global_idx

        # Labeling: Explicitly synthetic
        creator_name = f"[SYNTHETIC-BENCHMARK] Creator {target_idx:05d}"
        platform_id = f"synth_yt_{target_idx:05d}"
        profile_url = f"https://youtube.com/@synth_yt_{target_idx:05d}"
        candidate_source = "https://incubrix.internal/benchmark_fixtures"

        # Content dates:
        # Most have active recent content; some have inactive content > 90 days ago
        is_inactive = (idx % 8 == 0)
        if is_inactive:
            content_dates = [
                (now - timedelta(days=95)).strftime("%Y-%m-%d"),
                (now - timedelta(days=120)).strftime("%Y-%m-%d"),
            ]
        else:
            content_dates = [
                (now - timedelta(days=4 + (idx % 15))).strftime("%Y-%m-%d"),
                (now - timedelta(days=16 + (idx % 20))).strftime("%Y-%m-%d"),
                (now - timedelta(days=32 + (idx % 20))).strftime("%Y-%m-%d"),
            ]

        content_urls = [
            f"https://youtube.com/watch?v=synth_{target_idx:05d}_v1",
            f"https://youtube.com/watch?v=synth_{target_idx:05d}_v2",
        ]

        # Creator type: 5% agency (Gate 2 failure)
        is_agency = (idx % 20 == 0)
        c_type = "agency" if is_agency else creator_types[idx % len(creator_types)]

        # Country: 5% non-target (Gate 3 failure)
        is_non_target_country = (idx % 20 == 1)
        country = "India" if is_non_target_country else countries[idx % len(countries)]
        language = "Hindi" if is_non_target_country else "English"

        # Evidence URLs: Some missing to trigger Gate 5 / Gate 6 needs_review
        missing_comm = (idx % 12 == 2)
        missing_work = (idx % 12 == 3)
        commercial_url = "" if missing_comm else f"https://creator{target_idx:05d}.gumroad.com/sponsor"
        workflow_url = "" if missing_work else f"https://creator{target_idx:05d}.substack.com/archive"

        # Contact info: Some missing to trigger Gate 7 needs_review
        missing_contact = (idx % 14 == 4)
        if missing_contact:
            contact_type = ""
            contact_val = ""
            contact_src = ""
            contact_active = ""
        else:
            contact_type = "email"
            contact_val = f"business@creator{target_idx:05d}.synthetic.test"
            contact_src = f"https://youtube.com/@synth_yt_{target_idx:05d}/about"
            contact_active = (now - timedelta(days=8 + (idx % 20))).strftime("%Y-%m-%d")

        checked_at = (now - timedelta(days=2 + (idx % 10))).isoformat()
        first_disc = (now - timedelta(days=20 + (idx % 30))).isoformat()

        record = {
            "creator_name": creator_name,
            "creator_type": c_type,
            "country": country,
            "language": language,
            "platform": "youtube",
            "platform_id": platform_id,
            "official_profile_url": profile_url,
            "candidate_source_url": candidate_source,
            "recent_content_urls": json.dumps(content_urls),
            "recent_content_dates": json.dumps(content_dates),
            "commercial_evidence_url": commercial_url,
            "workflow_need_evidence_url": workflow_url,
            "business_contact_type": contact_type,
            "business_contact_value": contact_val,
            "business_contact_source_url": contact_src,
            "business_contact_last_active": contact_active,
            "evidence_checked_at": checked_at,
            "qualification_status": "discovered",
            "disqualification_reasons": "[]",
            "score": "0.0",
            "priority": "",
            "first_discovered_at": first_disc,
            "last_checked_at": checked_at,
            "last_run_id": "benchmark_gen",
            "is_synthetic": "True",
        }
        records.append(record)

    return records


def write_benchmark_csv(records: List[Dict[str, Any]], output_path: Path) -> Path:
    """Save records to CSV with exact header columns."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0].keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return output_path


def main():
    benchmarks_dir = Path("data/benchmarks")
    benchmarks_dir.mkdir(parents=True, exist_ok=True)

    tier_sizes = [100, 1000, 5000]
    print("=== GENERATING SYNTHETIC BENCHMARK FIXTURES ===")
    for size in tier_sizes:
        records = generate_synthetic_dataset(size=size, duplicate_rate=0.10)
        out_file = benchmarks_dir / f"benchmark_{size}.csv"
        write_benchmark_csv(records, out_file)
        print(f"Generated {len(records)} records -> {out_file} ({out_file.stat().st_size:,} bytes)")

    print("\nBenchmark fixtures successfully generated in data/benchmarks/.")


if __name__ == "__main__":
    main()
