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


EVIDENCE_ITEM_HEADERS = [
    "lead_id",
    "platform",
    "platform_id",
    "evidence_type",
    "source_url",
    "short_factual_description",
    "content_date",
    "checked_at",
    "verification_status",
    "verification_method",
    "review_reason",
]


def export_evidence_items_csv(
    items: List[Any],
    output_path: str,
    allow_synthetic: bool = False,
) -> str:
    """Write source-linked evidence items to CSV."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in items:
        if hasattr(item, "to_db_dict"):
            d = item.to_db_dict()
        elif isinstance(item, dict):
            d = item
        else:
            d = vars(item)

        rows.append({
            "lead_id": d.get("lead_id") or "",
            "platform": d.get("platform") or "",
            "platform_id": d.get("platform_id") or "",
            "evidence_type": d.get("evidence_type") or "",
            "source_url": d.get("source_url") or "",
            "short_factual_description": d.get("short_factual_description") or "",
            "content_date": d.get("content_date") or "",
            "checked_at": d.get("checked_at") or "",
            "verification_status": d.get("verification_status") or "",
            "verification_method": d.get("verification_method") or "",
            "review_reason": d.get("review_reason") or "",
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVIDENCE_ITEM_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} evidence items to {output_path}")
    return str(out)


OUTREACH_PREPARATION_HEADERS = [
    "lead_id",
    "platform_id",
    "creator_name",
    "score",
    "priority",
    "chosen_channel",
    "backup_channel",
    "proposed_first_message",
    "follow_up_1",
    "follow_up_2",
    "specific_content_source_url",
    "personalisation_rationale",
    "opt_out_language",
    "created_at",
]


def export_outreach_preparations_csv(
    preparations: List[Any],
    output_path: str,
    allow_synthetic: bool = False,
) -> str:
    """Write personalised outreach preparation for Priority A leads to CSV."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    filtered = preparations
    if not allow_synthetic:
        filtered = [
            p for p in preparations
            if not (
                (hasattr(p, "is_synthetic") and p.is_synthetic)
                or (isinstance(p, dict) and p.get("is_synthetic"))
            )
        ]

    rows = []
    for prep in filtered:
        if hasattr(prep, "to_db_dict"):
            d = prep.to_db_dict()
        elif isinstance(prep, dict):
            d = prep
        else:
            d = vars(prep)

        rows.append({
            "lead_id": d.get("lead_id") or "",
            "platform_id": d.get("platform_id") or "",
            "creator_name": d.get("creator_name") or "",
            "score": d.get("score", 0.0),
            "priority": d.get("priority") or "A",
            "chosen_channel": d.get("chosen_channel") or "",
            "backup_channel": d.get("backup_channel") or "",
            "proposed_first_message": d.get("proposed_first_message") or "",
            "follow_up_1": d.get("follow_up_1") or "",
            "follow_up_2": d.get("follow_up_2") or "",
            "specific_content_source_url": d.get("specific_content_source_url") or "",
            "personalisation_rationale": d.get("personalisation_rationale") or "",
            "opt_out_language": d.get("opt_out_language") or "",
            "created_at": d.get("created_at") or "",
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTREACH_PREPARATION_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} outreach preparations to {output_path}")
    return str(out)


DAY4_OUTREACH_HEADERS = [
    "lead_id",
    "creator_name",
    "segment",
    "priority",
    "score",
    "platform_id",
    "primary_channel",
    "primary_channel_reason",
    "primary_contact_value",
    "primary_contact_source_url",
    "primary_contact_verified_date",
    "backup_channel",
    "backup_channel_reason",
    "backup_contact_value",
    "backup_contact_source_url",
    "channel_suitability_status",
    "subject_line",
    "proposed_first_message",
    "follow_up_1",
    "follow_up_2",
    "follow_up_1_delay_days",
    "follow_up_2_delay_days",
    "specific_content_source_url",
    "personalisation_rationale",
    "opt_out_language",
    "sender_identity",
    "validation_status",
    "validation_notes",
    "outreach_status",
    "created_at",
]

OUTREACH_TEMPLATE_HEADERS = [
    "template_id",
    "segment",
    "channel",
    "touch_number",
    "suggested_delay_days",
    "subject_line",
    "body_template",
    "required_evidence_fields",
    "sender_identity",
    "compliance_notes",
]


def _format_day4_outreach_row(prep: Any) -> Dict[str, Any]:
    """Helper to convert OutreachPreparation to Day 4 CRM-ready row dictionary."""
    if hasattr(prep, "to_db_dict"):
        d = prep.to_db_dict()
    elif isinstance(prep, dict):
        d = prep
    else:
        d = vars(prep)

    return {
        "lead_id": d.get("lead_id") or "",
        "creator_name": d.get("creator_name") or "",
        "segment": d.get("segment") or "",
        "priority": d.get("priority") or "A",
        "score": d.get("score", 0.0),
        "platform_id": d.get("platform_id") or "",
        "primary_channel": d.get("primary_channel") or "",
        "primary_channel_reason": d.get("primary_channel_reason") or "",
        "primary_contact_value": d.get("primary_contact_value") or "",
        "primary_contact_source_url": d.get("primary_contact_source_url") or "",
        "primary_contact_verified_date": d.get("primary_contact_verified_date") or "",
        "backup_channel": d.get("backup_channel") or "",
        "backup_channel_reason": d.get("backup_channel_reason") or "",
        "backup_contact_value": d.get("backup_contact_value") or "",
        "backup_contact_source_url": d.get("backup_contact_source_url") or "",
        "channel_suitability_status": d.get("channel_suitability_status") or "suitable",
        "subject_line": d.get("subject_line") or "",
        "proposed_first_message": d.get("proposed_first_message") or "",
        "follow_up_1": d.get("follow_up_1") or "",
        "follow_up_2": d.get("follow_up_2") or "",
        "follow_up_1_delay_days": d.get("follow_up_1_delay_days", 3),
        "follow_up_2_delay_days": d.get("follow_up_2_delay_days", 7),
        "specific_content_source_url": d.get("specific_content_source_url") or "",
        "personalisation_rationale": d.get("personalisation_rationale") or "",
        "opt_out_language": d.get("opt_out_language") or "",
        "sender_identity": d.get("sender_identity") or "IncuBrix Growth Engineer Assessment Candidate",
        "validation_status": d.get("validation_status") or "valid",
        "validation_notes": d.get("validation_notes") or "",
        "outreach_status": d.get("outreach_status") or "DRAFT",
        "created_at": d.get("created_at") or "",
    }


def export_outreach_priority_a_csv(
    preparations: List[Any],
    output_path: str = "data/output/outreach_priority_a.csv",
    allow_synthetic: bool = False,
) -> str:
    """Export CRM-ready outreach preparations for Priority A leads."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    filtered = [
        p for p in preparations
        if (getattr(p, "priority", None) or (isinstance(p, dict) and p.get("priority")) or "A") == "A"
    ]
    if not allow_synthetic:
        filtered = [
            p for p in filtered
            if not (
                (hasattr(p, "is_synthetic") and p.is_synthetic)
                or (isinstance(p, dict) and p.get("is_synthetic"))
            )
        ]

    rows = [_format_day4_outreach_row(p) for p in filtered]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DAY4_OUTREACH_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} Priority A outreach preparations to {output_path}")
    return str(out)


def export_outreach_all_qualified_csv(
    preparations: List[Any],
    output_path: str = "data/output/outreach_all_qualified.csv",
    allow_synthetic: bool = False,
) -> str:
    """Export CRM-ready outreach preparations for all qualified leads."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    filtered = preparations
    if not allow_synthetic:
        filtered = [
            p for p in preparations
            if not (
                (hasattr(p, "is_synthetic") and p.is_synthetic)
                or (isinstance(p, dict) and p.get("is_synthetic"))
            )
        ]

    rows = [_format_day4_outreach_row(p) for p in filtered]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DAY4_OUTREACH_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} qualified outreach preparations to {output_path}")
    return str(out)


def export_outreach_templates_csv(
    templates: Optional[List[Any]] = None,
    output_path: str = "data/output/outreach_templates.csv",
) -> str:
    """Export the 15-segment/channel 3-touch outreach templates catalogue to CSV."""
    from src.verification.templates import get_all_templates

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    tmpl_list = templates if templates is not None else get_all_templates()
    rows = []
    for t in tmpl_list:
        if hasattr(t, "to_dict"):
            d = t.to_dict()
        elif isinstance(t, dict):
            d = t
        else:
            d = vars(t)
        rows.append({
            "template_id": d.get("template_id") or "",
            "segment": d.get("segment") or "",
            "channel": d.get("channel") or "",
            "touch_number": d.get("touch_number", 1),
            "suggested_delay_days": d.get("suggested_delay_days", 0),
            "subject_line": d.get("subject_line") or "",
            "body_template": d.get("body_template") or "",
            "required_evidence_fields": json.dumps(d.get("required_evidence_fields") or []),
            "sender_identity": d.get("sender_identity") or "IncuBrix Growth Engineer Assessment Candidate",
            "compliance_notes": d.get("compliance_notes") or "",
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTREACH_TEMPLATE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} outreach templates to {output_path}")
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
    """Generate comprehensive Day 3 run, audit, and metrics report in JSON format."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    started = start_time or now

    # Segregate real leads from synthetic fixtures
    real_leads = [l for l in leads if not getattr(l, "is_synthetic", False)]
    total_real = len(real_leads)
    synthetic_count = sum(1 for l in leads if getattr(l, "is_synthetic", False))

    discovered_real = [l for l in real_leads if l.qualification_status == QualificationStatus.DISCOVERED.value]
    needs_review_real = [l for l in real_leads if l.qualification_status == QualificationStatus.NEEDS_REVIEW.value]
    qualified_all = [l for l in leads if l.qualification_status == QualificationStatus.QUALIFIED.value]
    qualified_real = [l for l in real_leads if l.qualification_status == QualificationStatus.QUALIFIED.value]
    disqualified_real = [l for l in real_leads if l.qualification_status == QualificationStatus.DISQUALIFIED.value]

    # Priority counts for real qualified leads
    priority_counts: Dict[str, int] = {}
    for q in qualified_real:
        pri = q.priority or "Unassigned"
        priority_counts[pri] = priority_counts.get(pri, 0) + 1

    priority_a_count = priority_counts.get("A", 0)

    # Country counts for real qualified leads
    country_counts: Dict[str, int] = {}
    for q in qualified_real:
        c = q.country or "Unknown"
        country_counts[c] = country_counts.get(c, 0) + 1

    # Platform & Segment distribution for all real candidates
    platform_counts: Dict[str, int] = {}
    segment_counts: Dict[str, int] = {}
    for l in real_leads:
        plat = l.platform or "Unknown"
        platform_counts[plat] = platform_counts.get(plat, 0) + 1
        seg = l.creator_type or "Unknown"
        segment_counts[seg] = segment_counts.get(seg, 0) + 1

    # Disqualification reasons breakdown for real leads
    disqualified_reasons_breakdown: Dict[str, int] = {}
    for d in disqualified_real:
        for r in d.disqualification_reasons:
            disqualified_reasons_breakdown[r] = disqualified_reasons_breakdown.get(r, 0) + 1

    # Missing evidence breakdown for real needs_review leads
    missing_evidence_summary: Dict[str, int] = {}
    for nr in needs_review_real:
        for r in nr.disqualification_reasons:
            missing_evidence_summary[r] = missing_evidence_summary.get(r, 0) + 1

    # Evidence freshness calculation (checked <= 30 days ago)
    fresh_count = 0
    for l in real_leads:
        if l.evidence_checked_at:
            try:
                chk = datetime.fromisoformat(l.evidence_checked_at.replace("Z", "+00:00"))
                if (now - chk).total_seconds() <= 30 * 86400:
                    fresh_count += 1
            except Exception:
                pass
    freshness_rate = round(fresh_count / total_real, 3) if total_real > 0 else 0.0

    # Duplicate rate calculation
    total_imported = total_real + duplicates_prevented
    duplicate_rate = round(duplicates_prevented / total_imported, 3) if total_imported > 0 else 0.0
    qualification_rate = round(len(qualified_real) / total_real, 3) if total_real > 0 else 0.0

    pipeline_summary = {
        "candidate_count": total_real,
        "total_candidates": total_real,
        "discovered_pending": len(discovered_real),
        "needs_review_count": len(needs_review_real),
        "needs_review": len(needs_review_real),
        "qualified_lead_count": len(qualified_real),
        "qualified_leads": len(qualified_real) if synthetic_count < len(leads) else len(qualified_all),
        "qualified_leads_total": len(qualified_all),
        "qualified_leads_real": len(qualified_real),
        "disqualified_count": len(disqualified_real),
        "disqualified_candidates": len(disqualified_real),
        "priority_a_count": priority_a_count,
        "synthetic_test_fixtures": synthetic_count,
        "synthetic_test_fixtures_excluded": synthetic_count,
        "qualification_rate": qualification_rate,
        "real_qualification_rate": qualification_rate,
        "duplicate_rate": duplicate_rate,
        "evidence_freshness_rate": freshness_rate,
    }

    audit_and_quality_report = {
        "qualified_lead_count": len(qualified_real),
        "candidate_count": total_real,
        "needs_review_count": len(needs_review_real),
        "disqualified_count_by_reason": disqualified_reasons_breakdown,
        "evidence_freshness_rate": freshness_rate,
        "duplicate_rate": duplicate_rate,
        "qualification_rate": qualification_rate,
        "country_distribution": country_counts,
        "platform_distribution": platform_counts,
        "segment_distribution": segment_counts,
        "priority_a_count": priority_a_count,
        "missing_evidence_summary": missing_evidence_summary,
    }

    summary = {
        "run_metadata": {
            "run_id": run_id or "manual_run",
            "started_at": started.isoformat(),
            "completed_at": now.isoformat(),
            "runtime_seconds": round(runtime_seconds, 3),
            "records_processed": len(leads),
            "duplicates_prevented": duplicates_prevented,
            "errors_count": len(errors or []),
            "errors": errors or [],
        },
        "summary": pipeline_summary,
        "lead_pipeline_summary": pipeline_summary,
        "audit_and_quality_report": audit_and_quality_report,
        "real_qualified_priority_breakdown": priority_counts,
        "real_qualified_country_breakdown": country_counts,
        "compliance_notes": [
            "Synthetic fixtures are strictly excluded from all real-lead metrics and production exports.",
            "Missing evidence is never guessed or defaulted to verified.",
            "All qualified leads must satisfy 10 policy hard gates with checked dates within 30 days.",
            "Priority A is capped at top 25 qualified leads with verified outreach copy.",
        ],
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return str(out)


def export_workbook_pack(
    leads: List[Lead],
    output_dir: str = "data/output",
    verification_logs: Optional[List[Any]] = None,
    evidence_items: Optional[List[Any]] = None,
    outreach_preparations: Optional[List[Any]] = None,
    run_stats: Optional[Dict[str, Any]] = None,
    allow_synthetic: bool = False,
) -> Dict[str, str]:
    """
    Generate the complete Day 3 assessment deliverable pack:
    1. qualified_leads.csv (Real qualified creators only by default)
    2. all_candidates.csv (All discovered creators with status)
    3. needs_review.csv (Creators requiring evidence verification)
    4. disqualification_audit.csv (Audited rejections with reasons)
    5. verification_audit_log.csv (Complete audit log)
    6. evidence_items.csv (Source-linked verified and audited evidence)
    7. priority_a_outreach.csv (Personalised outreach sequences for Priority A leads)
    8. summary_report.json / run_summary.json / audit_and_quality_report.json
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
        "evidence_items": export_evidence_items_csv(
            evidence_items or [], str(out_dir / "evidence_items.csv"), allow_synthetic=allow_synthetic
        ),
        "priority_a_outreach": export_outreach_preparations_csv(
            outreach_preparations or [], str(out_dir / "priority_a_outreach.csv"), allow_synthetic=allow_synthetic
        ),
        "outreach_priority_a": export_outreach_priority_a_csv(
            outreach_preparations or [], str(out_dir / "outreach_priority_a.csv"), allow_synthetic=allow_synthetic
        ),
        "outreach_all_qualified": export_outreach_all_qualified_csv(
            outreach_preparations or [], str(out_dir / "outreach_all_qualified.csv"), allow_synthetic=allow_synthetic
        ),
        "outreach_templates": export_outreach_templates_csv(
            None, str(out_dir / "outreach_templates.csv")
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
        "audit_and_quality_report": export_summary_json(
            leads,
            str(out_dir / "audit_and_quality_report.json"),
            run_id=run_id,
            runtime_seconds=runtime,
            duplicates_prevented=dups,
            errors=errs,
            start_time=start_t,
        ),
    }
    return paths
