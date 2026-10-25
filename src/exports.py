"""
Export engine for IncuBrix Lead Discovery Engine.
Generates CSVs and JSON summaries adhering to workbook schema.
Explicitly distinguishes candidates from qualified leads and audited rejections.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.logging_config import get_logger
from src.models import Lead, QualificationStatus

logger = get_logger("exports")

ASSESSMENT_WORKBOOK_HEADERS = [
    "creator_name",
    "creator_type",
    "country",
    "language",
    "platform",
    "platform_id",
    "official_profile_url",
    "candidate_source_url",
    "recent_content_urls",
    "recent_content_dates",
    "commercial_evidence_url",
    "workflow_need_evidence_url",
    "business_contact_type",
    "business_contact_value",
    "business_contact_source_url",
    "business_contact_last_active",
    "evidence_checked_at",
    "qualification_status",
    "disqualification_reasons",
    "score",
    "priority",
    "first_discovered_at",
    "last_checked_at",
    "last_run_id",
]


def format_lead_row(lead: Lead) -> Dict[str, Any]:
    """Format a Lead instance into exact workbook dictionary representation."""
    return {
        "creator_name": lead.creator_name or "",
        "creator_type": lead.creator_type or "",
        "country": lead.country or "",
        "language": lead.language or "English",
        "platform": lead.platform or "",
        "platform_id": lead.platform_id or "",
        "official_profile_url": lead.official_profile_url or "",
        "candidate_source_url": lead.candidate_source_url or "",
        "recent_content_urls": json.dumps(lead.recent_content_urls) if lead.recent_content_urls else "[]",
        "recent_content_dates": json.dumps(lead.recent_content_dates) if lead.recent_content_dates else "[]",
        "commercial_evidence_url": lead.commercial_evidence_url or "",
        "workflow_need_evidence_url": lead.workflow_need_evidence_url or "",
        "business_contact_type": lead.business_contact_type or "",
        "business_contact_value": lead.business_contact_value or "",
        "business_contact_source_url": lead.business_contact_source_url or "",
        "business_contact_last_active": lead.business_contact_last_active or "",
        "evidence_checked_at": lead.evidence_checked_at or "",
        "qualification_status": lead.qualification_status or QualificationStatus.DISCOVERED.value,
        "disqualification_reasons": json.dumps(lead.disqualification_reasons) if lead.disqualification_reasons else "[]",
        "score": lead.score,
        "priority": lead.priority or "",
        "first_discovered_at": lead.first_discovered_at or "",
        "last_checked_at": lead.last_checked_at or "",
        "last_run_id": lead.last_run_id or "",
    }


def export_leads_csv(
    leads: List[Lead],
    output_path: str,
    filter_status: Optional[str] = None,
    allow_synthetic: bool = False,
) -> str:
    """
    Write leads to a CSV file matching the assessment workbook format.
    Optional filter_status filters by 'qualified', 'needs_review', 'discovered', or 'disqualified'.
    Qualified export strictly filters out synthetic test fixtures unless allow_synthetic=True.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    filtered = leads
    if filter_status:
        filtered = [l for l in leads if l.qualification_status.lower() == filter_status.lower()]

    # Critical integrity: qualified export must NEVER include synthetic fixtures
    if filter_status and filter_status.lower() == "qualified" and not allow_synthetic:
        filtered = [l for l in filtered if not getattr(l, "is_synthetic", False)]

    rows = [format_lead_row(lead) for lead in filtered]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ASSESSMENT_WORKBOOK_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} rows to {output_path} (filter={filter_status}, allow_synthetic={allow_synthetic})")
    return str(out)


VERIFICATION_LOG_HEADERS = [
    "id",
    "timestamp",
    "run_id",
    "platform",
    "platform_id",
    "action",
    "status_before",
    "status_after",
    "score",
    "priority",
    "disqualification_reasons",
    "details",
]


def export_verification_logs_csv(
    logs: List[Any],
    output_path: str,
) -> str:
    """Write verification audit logs to a CSV file for compliance auditing."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for log in logs:
        if hasattr(log, "to_db_dict"):
            d = log.to_db_dict()
        elif isinstance(log, dict):
            d = log
        else:
            d = vars(log)

        rows.append({
            "id": d.get("id") or "",
            "timestamp": d.get("timestamp") or "",
            "run_id": d.get("run_id") or "",
            "platform": d.get("platform") or "",
            "platform_id": d.get("platform_id") or "",
            "action": d.get("action") or "",
            "status_before": d.get("status_before") or "",
            "status_after": d.get("status_after") or "",
            "score": d.get("score", 0.0),
            "priority": d.get("priority") or "",
            "disqualification_reasons": json.dumps(d.get("disqualification_reasons", [])) if isinstance(d.get("disqualification_reasons"), list) else str(d.get("disqualification_reasons", "")),
            "details": json.dumps(d.get("details", {})) if isinstance(d.get("details"), dict) else str(d.get("details", "")),
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VERIFICATION_LOG_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} verification audit log records to {output_path}")
    return str(out)


def export_summary_json(
    leads: List[Lead],
    output_path: str,
    run_id: Optional[str] = None,
    runtime_seconds: float = 0.0,
    duplicates_prevented: int = 0,
    errors: Optional[List[str]] = None,
    start_time: Optional[datetime] = None,
) -> str:
    """Generate comprehensive run and metrics report in JSON format."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    started = start_time or now

    total = len(leads)
    discovered = [l for l in leads if l.qualification_status == QualificationStatus.DISCOVERED.value]
    needs_review = [l for l in leads if l.qualification_status == QualificationStatus.NEEDS_REVIEW.value]
    qualified_all = [l for l in leads if l.qualification_status == QualificationStatus.QUALIFIED.value]
    qualified_real = [l for l in qualified_all if not getattr(l, "is_synthetic", False)]
    disqualified = [l for l in leads if l.qualification_status == QualificationStatus.DISQUALIFIED.value]
    synthetic_count = sum(1 for l in leads if getattr(l, "is_synthetic", False))

    priority_counts: Dict[str, int] = {}
    for q in qualified_real:
        pri = q.priority or "Unassigned"
        priority_counts[pri] = priority_counts.get(pri, 0) + 1

    country_counts: Dict[str, int] = {}
    for q in qualified_real:
        c = q.country or "Unknown"
        country_counts[c] = country_counts.get(c, 0) + 1

    pipeline_summary = {
        "total_candidates": total,
        "discovered_pending": len(discovered),
        "needs_review": len(needs_review),
        "qualified_leads": len(qualified_real) if synthetic_count < total else len(qualified_all),
        "qualified_leads_total": len(qualified_all),
        "qualified_leads_real": len(qualified_real),
        "synthetic_test_fixtures": synthetic_count,
        "disqualified_candidates": len(disqualified),
        "real_qualification_rate": round(len(qualified_real) / total, 3) if total > 0 else 0.0,
    }

    summary = {
        "run_metadata": {
            "run_id": run_id or "manual_run",
            "started_at": started.isoformat(),
            "completed_at": now.isoformat(),
            "runtime_seconds": round(runtime_seconds, 3),
            "records_processed": total,
            "duplicates_prevented": duplicates_prevented,
            "errors_count": len(errors or []),
            "errors": errors or [],
        },
        "summary": pipeline_summary,
        "lead_pipeline_summary": pipeline_summary,
        "real_qualified_priority_breakdown": priority_counts,
        "real_qualified_country_breakdown": country_counts,
        "compliance_notes": [
            "Synthetic fixtures are strictly excluded from real qualified exports.",
            "Missing evidence is never guessed or defaulted to verified.",
            "All qualified leads must satisfy 10 policy hard gates with checked dates within 30 days.",
        ],
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return str(out)


def export_workbook_pack(
    leads: List[Lead],
    output_dir: str = "data/output",
    verification_logs: Optional[List[Any]] = None,
    run_stats: Optional[Dict[str, Any]] = None,
    allow_synthetic: bool = False,
) -> Dict[str, str]:
    """
    Generate the complete assessment deliverable pack:
    1. qualified_leads.csv (Real qualified creators only by default)
    2. all_candidates.csv (All discovered creators with status)
    3. needs_review.csv (Creators requiring evidence verification)
    4. disqualification_audit.csv (Audited rejections with reasons)
    5. verification_audit_log.csv (Complete audit log)
    6. summary_report.json / run_summary.json (Run summary & metrics)
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = run_stats or {}
    run_id = stats.get("run_id")
    runtime = stats.get("runtime_seconds", 0.0)
    dups = stats.get("duplicates_prevented", 0)
    errs = stats.get("errors", [])
    start_t = stats.get("start_time")

    paths = {
        "qualified_leads": export_leads_csv(
            leads, str(out_dir / "qualified_leads.csv"), filter_status="qualified", allow_synthetic=allow_synthetic
        ),
        "all_candidates": export_leads_csv(
            leads, str(out_dir / "all_candidates.csv")
        ),
        "needs_review": export_leads_csv(
            leads, str(out_dir / "needs_review.csv"), filter_status="needs_review"
        ),
        "disqualification_audit": export_leads_csv(
            leads, str(out_dir / "disqualification_audit.csv"), filter_status="disqualified"
        ),
        "verification_audit": export_verification_logs_csv(
            verification_logs or [], str(out_dir / "verification_audit_log.csv")
        ),
        "summary_report": export_summary_json(
            leads,
            str(out_dir / "summary_report.json"),
            run_id=run_id,
            runtime_seconds=runtime,
            duplicates_prevented=dups,
            errors=errs,
            start_time=start_t,
        ),
        "run_summary": export_summary_json(
            leads,
            str(out_dir / "run_summary.json"),
            run_id=run_id,
            runtime_seconds=runtime,
            duplicates_prevented=dups,
            errors=errs,
            start_time=start_t,
        ),
    }
    return paths
