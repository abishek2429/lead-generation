"""
Deduplication and URL canonicalization engine.
Ensures stable platform IDs and canonical URLs prevent duplicates and enable deterministic merging.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.models import Lead

# Parameters that typically convey tracking or session state and should be stripped for canonical matching
STRIPPED_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
    "source",
    "fbclid",
    "gclid",
    "si",
    "feature",
    "sub_confirmation",
    "t",
}


def canonicalize_url(url: Optional[str]) -> str:
    """
    Produce a stable canonical URL:
    - Lowercase domain and scheme
    - Strip trailing slashes and default ports
    - Remove tracking/campaign query parameters
    - Standardize common platform domains (e.g., www.youtube.com -> youtube.com)
    """
    if not url:
        return ""

    raw = url.strip()
    if not raw:
        return ""

    # Ensure scheme
    if not re.match(r"^[a-zA-Z]+://", raw):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.rstrip("/").lower()

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Normalize common domains
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove default ports
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if (scheme == "https" and port == "443") or (scheme == "http" and port == "80"):
            netloc = host

    path = parsed.path.rstrip("/")
    if not path:
        path = ""

    # Standardize YouTube paths: /c/name, /user/name, /@name
    if netloc in ("youtube.com", "m.youtube.com"):
        netloc = "youtube.com"
        # preserve case for handle or channel ID, but strip redundant segments
        if path.startswith("/c/"):
            path = path[2:]  # /c/handle -> /handle
        elif path.startswith("/user/"):
            path = path[5:]

    # Filter query parameters
    clean_params = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=False):
            if k.lower() not in STRIPPED_QUERY_PARAMS:
                clean_params.append((k, v))

    clean_query = urlencode(sorted(clean_params)) if clean_params else ""

    # Reconstruct canonical URL (fragment is removed)
    canonical = urlunparse((scheme, netloc, path, "", clean_query, ""))
    return canonical.rstrip("/")


def extract_platform_key(platform: str, platform_id: str) -> str:
    """Generate normalized tuple string for platform-level matching."""
    norm_platform = platform.strip().lower()
    norm_id = platform_id.strip().lower()
    return f"{norm_platform}:{norm_id}"


def merge_leads(existing: Lead, incoming: Lead, run_id: Optional[str] = None) -> Tuple[Lead, bool]:
    """
    Deterministically merge incoming lead data into existing record.
    Returns (merged_lead, has_changes).
    
    Merge rules:
    - first_discovered_at: retains the earliest discovery timestamp.
    - evidence & content URLs/dates: union sets, preserving freshness.
    - commercial & workflow evidence: fills missing fields if incoming has them.
    - business contact: fills missing fields if incoming has them.
    - updates last_checked_at and last_run_id to latest.
    """
    has_changes = False

    # Earliest discovery timestamp
    earliest_discovered = existing.first_discovered_at
    if incoming.first_discovered_at and incoming.first_discovered_at < earliest_discovered:
        earliest_discovered = incoming.first_discovered_at
        has_changes = True

    # Merge content URLs
    existing_content_set = set(existing.recent_content_urls)
    new_content_urls = list(existing.recent_content_urls)
    for url in incoming.recent_content_urls:
        if url and url not in existing_content_set:
            new_content_urls.append(url)
            existing_content_set.add(url)
            has_changes = True

    # Merge content dates (sorted descending)
    all_dates = set(existing.recent_content_dates).union(set(incoming.recent_content_dates))
    merged_dates = sorted([d for d in all_dates if d], reverse=True)
    if merged_dates != existing.recent_content_dates:
        has_changes = True

    # Evidence URLs (incoming fills gaps or updates if valid)
    commercial_url = existing.commercial_evidence_url
    if incoming.commercial_evidence_url and incoming.commercial_evidence_url != existing.commercial_evidence_url:
        commercial_url = incoming.commercial_evidence_url
        has_changes = True

    workflow_url = existing.workflow_need_evidence_url
    if incoming.workflow_need_evidence_url and incoming.workflow_need_evidence_url != existing.workflow_need_evidence_url:
        workflow_url = incoming.workflow_need_evidence_url
        has_changes = True

    # Contact details
    contact_type = incoming.business_contact_type or existing.business_contact_type
    contact_val = incoming.business_contact_value or existing.business_contact_value
    contact_src = incoming.business_contact_source_url or existing.business_contact_source_url
    contact_active = incoming.business_contact_last_active or existing.business_contact_last_active

    if (
        contact_type != existing.business_contact_type
        or contact_val != existing.business_contact_value
        or contact_src != existing.business_contact_source_url
        or contact_active != existing.business_contact_last_active
    ):
        has_changes = True

    evidence_checked = incoming.evidence_checked_at or existing.evidence_checked_at
    if incoming.evidence_checked_at and incoming.evidence_checked_at != existing.evidence_checked_at:
        has_changes = True

    country = incoming.country or existing.country
    if incoming.country and incoming.country != existing.country:
        has_changes = True

    creator_type = incoming.creator_type or existing.creator_type
    creator_name = incoming.creator_name or existing.creator_name

    merged = Lead(
        id=existing.id,
        creator_name=creator_name,
        creator_type=creator_type,
        country=country,
        language=incoming.language or existing.language or "English",
        platform=existing.platform,
        platform_id=existing.platform_id,
        official_profile_url=existing.official_profile_url or incoming.official_profile_url,
        candidate_source_url=existing.candidate_source_url,
        recent_content_urls=new_content_urls,
        recent_content_dates=merged_dates,
        commercial_evidence_url=commercial_url,
        workflow_need_evidence_url=workflow_url,
        business_contact_type=contact_type,
        business_contact_value=contact_val,
        business_contact_source_url=contact_src,
        business_contact_last_active=contact_active,
        evidence_checked_at=evidence_checked,
        # Preserve status unless re-qualified
        qualification_status=existing.qualification_status,
        disqualification_reasons=existing.disqualification_reasons,
        score=existing.score,
        priority=existing.priority,
        first_discovered_at=earliest_discovered,
        last_checked_at=incoming.last_checked_at or existing.last_checked_at,
        last_run_id=run_id or incoming.last_run_id or existing.last_run_id,
    )
    return merged, has_changes


def deduplicate_batch(
    existing_leads: List[Lead],
    incoming_candidates: List[Lead],
    run_id: Optional[str] = None,
) -> Tuple[List[Lead], List[Lead], Dict[str, int]]:
    """
    Process incoming candidates against existing repository.
    Returns:
    - to_insert: brand new candidates
    - to_update: existing leads updated with new evidence
    - stats: summary counts
    """
    # Index existing by platform_key and canonical profile URL
    platform_map: Dict[str, Lead] = {}
    url_map: Dict[str, Lead] = {}

    # Track existing keys
    existing_pkeys: Set[str] = set()
    for lead in existing_leads:
        pkey = extract_platform_key(lead.platform, lead.platform_id)
        existing_pkeys.add(pkey)
        platform_map[pkey] = lead
        canon_url = canonicalize_url(lead.official_profile_url)
        if canon_url:
            url_map[canon_url] = lead

    to_insert_map: Dict[str, Lead] = {}
    to_update_map: Dict[str, Lead] = {}
    exact_duplicates = 0

    for candidate in incoming_candidates:
        # Standardize URLs
        candidate.official_profile_url = canonicalize_url(candidate.official_profile_url)
        candidate.candidate_source_url = canonicalize_url(candidate.candidate_source_url)
        if candidate.commercial_evidence_url:
            candidate.commercial_evidence_url = canonicalize_url(candidate.commercial_evidence_url)
        if candidate.workflow_need_evidence_url:
            candidate.workflow_need_evidence_url = canonicalize_url(candidate.workflow_need_evidence_url)
        if candidate.business_contact_source_url:
            candidate.business_contact_source_url = canonicalize_url(candidate.business_contact_source_url)

        cand_pkey = extract_platform_key(candidate.platform, candidate.platform_id)
        cand_url = canonicalize_url(candidate.official_profile_url)

        # Check existing match
        match = platform_map.get(cand_pkey) or (url_map.get(cand_url) if cand_url else None)

        if match:
            # Found existing: perform deterministic merge
            merged, changed = merge_leads(match, candidate, run_id=run_id)
            match_pkey = extract_platform_key(match.platform, match.platform_id)

            # Update in-memory indexes
            platform_map[match_pkey] = merged
            platform_map[cand_pkey] = merged
            match_url = canonicalize_url(merged.official_profile_url)
            if match_url:
                url_map[match_url] = merged
            if cand_url:
                url_map[cand_url] = merged

            if changed:
                if match_pkey in existing_pkeys:
                    to_update_map[match_pkey] = merged
                else:
                    to_insert_map[match_pkey] = merged
            else:
                exact_duplicates += 1
        else:
            # Brand new candidate
            to_insert_map[cand_pkey] = candidate
            platform_map[cand_pkey] = candidate
            if cand_url:
                url_map[cand_url] = candidate

    stats = {
        "total_incoming": len(incoming_candidates),
        "new_records": len(to_insert_map),
        "merged_records": len(to_update_map),
        "exact_duplicates": exact_duplicates,
    }

    return list(to_insert_map.values()), list(to_update_map.values()), stats
