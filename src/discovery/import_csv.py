"""
CSV Import adapter for creator discovery.
Parses candidate files, normalizes headers, and outputs Candidate Lead objects in 'discovered' status.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.deduplication import canonicalize_url
from src.discovery.base import BaseDiscovery
from src.logging_config import get_logger
from src.models import Lead, QualificationStatus

logger = get_logger("import_csv")

# Header mapping variations
COLUMN_ALIASES: Dict[str, List[str]] = {
    "creator_name": ["creator_name", "creator", "channel_name", "name", "creator name", "channel name"],
    "creator_type": ["creator_type", "type", "segment", "category", "creator type"],
    "country": ["country", "location", "geography"],
    "language": ["language", "lang", "primary_language"],
    "platform": ["platform", "channel_platform", "source_platform"],
    "platform_id": ["platform_id", "channel_id", "channel id", "handle", "creator_id", "id"],
    "official_profile_url": ["official_profile_url", "profile_url", "channel_url", "profile url", "channel url", "url"],
    "candidate_source_url": ["candidate_source_url", "source_url", "candidate source", "source"],
    "recent_content_urls": ["recent_content_urls", "content_urls", "recent_videos", "recent_episodes", "recent content urls"],
    "recent_content_dates": ["recent_content_dates", "content_dates", "video_dates", "recent content dates"],
    "commercial_evidence_url": ["commercial_evidence_url", "commercial_evidence", "monetization_url", "offer_url", "commercial evidence url"],
    "workflow_need_evidence_url": ["workflow_need_evidence_url", "workflow_need_evidence", "workflow_url", "workflow need evidence url"],
    "business_contact_type": ["business_contact_type", "contact_type", "channel_type", "business contact type"],
    "business_contact_value": ["business_contact_value", "contact_value", "email", "business_email", "business contact value"],
    "business_contact_source_url": ["business_contact_source_url", "contact_source_url", "contact_source", "business contact source url"],
    "business_contact_last_active": ["business_contact_last_active", "contact_last_active", "business contact last active"],
    "evidence_checked_at": ["evidence_checked_at", "checked_at", "evidence checked at"],
    "qualification_status": ["qualification_status", "status", "qualification status"],
    "disqualification_reasons": ["disqualification_reasons", "reasons", "disqualification reasons"],
    "score": ["score", "qualification_score"],
    "priority": ["priority", "priority_level"],
    "first_discovered_at": ["first_discovered_at", "discovered_at", "first discovered at"],
    "last_checked_at": ["last_checked_at", "last checked at"],
    "last_run_id": ["last_run_id", "run_id"],
    "is_synthetic": ["is_synthetic", "synthetic", "is_fixture", "fixture", "test_fixture"],
}


def normalize_header(header: str) -> str:
    """Normalize a CSV header string to lowercase trimmed snake_case."""
    return header.strip().lower().replace(" ", "_").replace("-", "_")


def build_field_map(headers: List[str]) -> Dict[str, str]:
    """Map canonical Lead field names to matching CSV header column names."""
    field_map: Dict[str, str] = {}
    normalized_headers = {normalize_header(h): h for h in headers}

    for target_field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = normalize_header(alias)
            if norm_alias in normalized_headers:
                field_map[target_field] = normalized_headers[norm_alias]
                break
    return field_map


class CSVDiscovery(BaseDiscovery):
    """Imports candidate creators from CSV files."""

    def __init__(self, source_name: str = "CSV Import"):
        super().__init__(source_name=source_name)

    def parse_csv(
        self,
        file_source: Union[str, Path, io.StringIO, io.BytesIO],
        run_id: Optional[str] = None,
        default_status: str = QualificationStatus.DISCOVERED.value,
    ) -> Tuple[List[Lead], List[str]]:
        """
        Parse CSV content into a list of Lead candidate instances.
        Returns (leads, error_messages).
        """
        leads: List[Lead] = []
        errors: List[str] = []

        # Read content
        text_data = ""
        if isinstance(file_source, (str, Path)):
            p = Path(file_source)
            if not p.is_file():
                errors.append(f"File not found: {p}")
                return leads, errors
            for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    with open(p, "r", encoding=encoding) as f:
                        text_data = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            if not text_data:
                errors.append(f"Could not decode file {p} with supported encodings.")
                return leads, errors
        elif isinstance(file_source, io.BytesIO):
            for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    text_data = file_source.getvalue().decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
        elif isinstance(file_source, io.StringIO):
            text_data = file_source.getvalue()
        else:
            errors.append(f"Unsupported file source type: {type(file_source)}")
            return leads, errors

        # Parse CSV rows
        f_stream = io.StringIO(text_data)
        reader = csv.DictReader(f_stream)
        if not reader.fieldnames:
            errors.append("CSV file has no headers.")
            return leads, errors

        field_map = build_field_map(reader.fieldnames)

        # Check required fields
        required_targets = ["creator_name", "platform", "platform_id", "official_profile_url"]
        missing_required = [req for req in required_targets if req not in field_map]
        if missing_required:
            errors.append(f"CSV missing mandatory columns: {', '.join(missing_required)}")
            return leads, errors

        row_idx = 1
        for row in reader:
            row_idx += 1
            try:
                # Extract mapped values
                creator_name = (row.get(field_map["creator_name"]) or "").strip()
                if not creator_name:
                    continue  # skip empty spacer rows

                creator_type = (row.get(field_map.get("creator_type", "")) or "podcaster").strip()
                platform = (row.get(field_map["platform"]) or "youtube").strip()
                platform_id = (row.get(field_map["platform_id"]) or "").strip()
                profile_url = (row.get(field_map["official_profile_url"]) or "").strip()

                if not platform_id and profile_url:
                    # fallback ID from URL
                    platform_id = profile_url.rstrip("/").split("/")[-1]

                candidate_src = (
                    row.get(field_map.get("candidate_source_url", "")) or "manual_csv_import"
                ).strip()

                lead_data: Dict[str, Any] = {
                    "creator_name": creator_name,
                    "creator_type": creator_type,
                    "country": row.get(field_map.get("country", "")),
                    "language": row.get(field_map.get("language", "")) or "English",
                    "platform": platform,
                    "platform_id": platform_id,
                    "official_profile_url": canonicalize_url(profile_url),
                    "candidate_source_url": canonicalize_url(candidate_src),
                    "recent_content_urls": row.get(field_map.get("recent_content_urls", "")),
                    "recent_content_dates": row.get(field_map.get("recent_content_dates", "")),
                    "commercial_evidence_url": row.get(field_map.get("commercial_evidence_url", "")),
                    "workflow_need_evidence_url": row.get(field_map.get("workflow_need_evidence_url", "")),
                    "business_contact_type": row.get(field_map.get("business_contact_type", "")),
                    "business_contact_value": row.get(field_map.get("business_contact_value", "")),
                    "business_contact_source_url": row.get(field_map.get("business_contact_source_url", "")),
                    "business_contact_last_active": row.get(field_map.get("business_contact_last_active", "")),
                    "evidence_checked_at": row.get(field_map.get("evidence_checked_at", "")),
                    "qualification_status": row.get(field_map.get("qualification_status", "")) or default_status,
                    "disqualification_reasons": row.get(field_map.get("disqualification_reasons", "")),
                    "score": float(row.get(field_map.get("score", "")) or 0.0),
                    "priority": row.get(field_map.get("priority", "")),
                    "first_discovered_at": row.get(field_map.get("first_discovered_at", "")),
                    "last_checked_at": row.get(field_map.get("last_checked_at", "")),
                    "last_run_id": run_id or row.get(field_map.get("last_run_id", "")),
                    "is_synthetic": row.get(field_map.get("is_synthetic", "")) or False,
                }

                # Construct validated Lead
                lead = Lead(**lead_data)
                leads.append(lead)

            except Exception as exc:
                errors.append(f"Row {row_idx}: Failed to parse creator record: {exc}")

        logger.info(f"Parsed {len(leads)} candidates from CSV with {len(errors)} warnings/errors.")
        return leads, errors

    def discover(self, file_path: str = "data/input/candidates.csv", **kwargs: Any) -> List[Lead]:
        """Discovery implementation from a CSV file path."""
        leads, _ = self.parse_csv(file_path, **kwargs)
        return leads
