"""
Export engine for IncuBrix Lead Discovery Engine.
Generates CSVs and JSON summaries adhering to workbook schema.
Explicitly distinguishes candidates from qualified leads and audited rejections.
"""

from __future__ import annotations

import csv
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
) -> str:
    """
    Write leads to a CSV file matching the assessment workbook format.
    Optional filter_status filters by 'qualified', 'discovered', or 'disqualified'.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    filtered = leads
    if filter_status:
        filtered = [l for l in leads if l.qualification_status.lower() == filter_status.lower()]

    rows = [format_lead_row(lead) for lead in filtered]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ASSESSMENT_WORKBOOK_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} rows to {output_path} (filter={filter_status})")
    return str(out)


def export_summary_json(leads: List[Lead], output_path: str) -> str:
    """Generate aggregate metrics report in JSON format."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    total = len(leads)
    discovered = [l for l in leads if l.qualification_status == QualificationStatus.DISCOVERED.value]
    qualified = [l for l in leads if l.qualification_status == QualificationStatus.QUALIFIED.value]
    disqualified = [l for l in leads if l.qualification_status == QualificationStatus.DISQUALIFIED.value]

    priority_counts: Dict[str, int] = {}
    for q in qualified:
        pri = q.priority or "Unassigned"
        priority_counts[pri] = priority_counts.get(pri, 0) + 1

    country_counts: Dict[str, int] = {}
    for q in qualified:
        c = q.country or "Unknown"
        country_counts[c] = country_counts.get(c, 0) + 1

    summary = {
        "summary": {
            "total_candidates": total,
            "discovered_pending": len(discovered),
            "qualified_leads": len(qualified),
            "disqualified_candidates": len(disqualified),
            "qualification_rate": round(len(qualified) / total, 3) if total > 0 else 0.0,
        },
        "qualified_priority_breakdown": priority_counts,
        "qualified_country_breakdown": country_counts,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return str(out)


def export_workbook_pack(leads: List[Lead], output_dir: str = "data/output") -> Dict[str, str]:
    """
    Generate the complete assessment deliverable pack:
    1. qualified_leads.csv (Qualified creators only)
    2. all_candidates.csv (All discovered creators with status)
    3. disqualification_audit.csv (Audited rejections with reasons)
    4. summary_report.json (Metrics breakdown)
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "qualified_leads": export_leads_csv(
            leads, str(out_dir / "qualified_leads.csv"), filter_status="qualified"
        ),
        "all_candidates": export_leads_csv(
            leads, str(out_dir / "all_candidates.csv")
        ),
        "disqualification_audit": export_leads_csv(
            leads, str(out_dir / "disqualification_audit.csv"), filter_status="disqualified"
        ),
        "summary_report": export_summary_json(
            leads, str(out_dir / "summary_report.json")
        ),
    }
    return paths
