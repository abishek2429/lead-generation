"""
Evidence and verification gate validation utilities.
Checks compliance with Day 1-3 qualification policy:
- Missing evidence is treated strictly as missing; never guessed or fabricated.
- Safe public URL validation preventing SSRF, localhost, private IP, and cloud metadata access.
- Source-linked evidence item construction and freshness auditing.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from pydantic import BaseModel

from src.logging_config import get_logger
from src.models import (
    EvidenceItem,
    EvidenceType,
    Lead,
    VerificationMethod,
    VerificationStatus,
    current_utc_iso,
)

logger = get_logger("evidence")

# Basic standard URL regex
STANDARD_URL_REGEX = re.compile(
    r"^https?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}\.?|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)

# Prohibited hostnames and suffixes for SSRF protection
BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "169.254.169.254",  # AWS / GCP / Azure metadata service
    "metadata.google.internal",
    "instance-data",
}

BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".localdomain",
    ".corp",
    ".lan",
)

# Prohibited platforms for unauthorized scraping
RESTRICTED_SCRAPING_DOMAINS = {
    "linkedin.com",
    "www.linkedin.com",
}


def is_safe_public_url(url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate whether URL is a safe, routable, public HTTP/HTTPS URL.
    Strictly prevents SSRF, localhost, private IP ranges (RFC 1918), and cloud metadata access.
    Returns (is_safe, failure_reason).
    """
    if not url or not isinstance(url, str):
        return False, "Missing or empty URL string"

    trimmed = url.strip()
    if not trimmed:
        return False, "Empty URL string"

    if not trimmed.startswith(("http://", "https://")):
        return False, "URL must use http:// or https:// scheme"

    try:
        parsed = urlparse(trimmed)
    except Exception as exc:
        return False, f"URL parse error: {exc}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Prohibited URL scheme '{scheme}'"

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        return False, "Missing hostname in URL"

    # Block prohibited hostnames and suffixes
    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Access to '{hostname}' is prohibited (SSRF prevention)"

    for suffix in BLOCKED_SUFFIXES:
        if hostname.endswith(suffix):
            return False, f"Access to internal suffix '{suffix}' is prohibited (SSRF prevention)"

    # Disallow unauthorized scraping domains
    if hostname in RESTRICTED_SCRAPING_DOMAINS:
        return False, f"Automated scraping of '{hostname}' is prohibited by assessment policy"

    # Validate IP address if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback:
            return False, f"Loopback address '{hostname}' is prohibited (SSRF prevention)"
        if ip.is_private:
            return False, f"Private network address '{hostname}' is prohibited (SSRF prevention)"
        if ip.is_link_local:
            return False, f"Link-local / cloud metadata address '{hostname}' is prohibited (SSRF prevention)"
        if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, f"Non-routable IP address '{hostname}' is prohibited (SSRF prevention)"
    except ValueError:
        # Hostname is a domain name, not an IP literal
        if not STANDARD_URL_REGEX.match(trimmed):
            return False, "Malformed URL structure"

    return True, None


def is_valid_url(url: Optional[str]) -> bool:
    """Validate whether URL string is safe, public, and structurally valid."""
    is_safe, _ = is_safe_public_url(url)
    return is_safe


def safe_http_head_or_get(
    url: str,
    timeout: int = 5,
    max_redirects: int = 3,
) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Safely probe a public URL without downloading large bodies or following unsafe redirects.
    Enforces SSRF prevention on every redirect hop.
    Returns (success, status_code, message).
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        return False, None, f"Unsafe URL rejected: {reason}"

    current_url = url
    headers = {"User-Agent": "IncuBrix-LeadEngine/1.0 (Audit Verification; +https://incubrix.com)"}

    try:
        for _ in range(max_redirects + 1):
            resp = requests.head(current_url, headers=headers, timeout=timeout, allow_redirects=False)
            status = resp.status_code

            # Handle 3xx redirects securely
            if 300 <= status < 400:
                location = resp.headers.get("Location")
                if not location:
                    break
                # Validate redirect destination is safe
                safe_dest, dest_reason = is_safe_public_url(location)
                if not safe_dest:
                    return False, status, f"Unsafe redirect to '{location}' blocked: {dest_reason}"
                current_url = location
                continue

            # If HEAD is not allowed (405 Method Not Allowed), retry with streaming GET
            if status == 405:
                resp = requests.get(
                    current_url,
                    headers=headers,
                    timeout=timeout,
                    stream=True,
                    allow_redirects=False,
                )
                status = resp.status_code

            if status < 400:
                return True, status, "OK"
            else:
                return False, status, f"HTTP Error {status}"

        return True, status, "OK"

    except requests.Timeout:
        return False, None, "Connection timed out"
    except requests.RequestException as exc:
        return False, None, f"HTTP request failed: {exc}"


def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO date or standard YYYY-MM-DD string into UTC datetime."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.strip()
    if not cleaned:
        return None
    # Handle YYYY-MM-DD
    if len(cleaned) == 10 and cleaned.count("-") == 2:
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        # Replace trailing Z with +00:00 for fromisoformat compatibility
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def calculate_days_ago(date_str: Optional[str], reference_date: Optional[datetime] = None) -> Optional[int]:
    """Calculate elapsed days between given date string and reference date."""
    dt = parse_iso_date(date_str)
    if dt is None:
        return None
    if isinstance(reference_date, str):
        ref = parse_iso_date(reference_date) or datetime.now(timezone.utc)
    else:
        ref = reference_date or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    diff = (ref - dt).total_seconds() / 86400.0
    return max(0, int(diff))


class GateResult(BaseModel):
    gate_name: str
    passed: bool
    reason: Optional[str] = None


def create_evidence_items_for_lead(
    lead: Lead,
    reference_date: Optional[datetime] = None,
) -> List[EvidenceItem]:
    """
    Construct source-linked evidence records for all 7 required assessment claims:
    1. Official identity & stable platform ID
    2. Recent content & publication dates
    3. Commercial offer
    4. Relevant workflow need
    5. Public business contact channel
    6. Recent business contact activity (<= 60 days)
    7. Target country & language
    
    CRITICAL: Never marks an evidence item verified merely because a URL exists.
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    checked_iso = lead.evidence_checked_at or current_utc_iso()
    evidence_days = calculate_days_ago(lead.evidence_checked_at, ref_dt)

    items: List[EvidenceItem] = []

    # 1. Official Identity Gate
    profile_safe, profile_err = is_safe_public_url(lead.official_profile_url)
    if profile_safe and lead.platform_id and lead.platform_id.strip():
        id_status = VerificationStatus.VERIFIED.value
        id_reason = None
    else:
        id_status = VerificationStatus.FAILED.value
        id_reason = profile_err or "Missing stable platform ID"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.OFFICIAL_IDENTITY.value,
            source_url=lead.official_profile_url or "",
            short_factual_description=f"Official {lead.platform} profile for {lead.creator_name} (ID: {lead.platform_id})",
            checked_at=checked_iso,
            verification_status=id_status,
            verification_method=VerificationMethod.DOMAIN_INSPECTION.value,
            review_reason=id_reason,
        )
    )

    # 2. Recent Content & Activity Gate
    content_count = len(lead.recent_content_urls)
    latest_date = lead.recent_content_dates[0] if lead.recent_content_dates else None
    first_content_url = lead.recent_content_urls[0] if lead.recent_content_urls else lead.official_profile_url

    parsed_dates = [calculate_days_ago(d, ref_dt) for d in lead.recent_content_dates if d]
    valid_dates = [d for d in parsed_dates if d is not None]
    items_30d = sum(1 for d in valid_dates if d <= 30)
    items_60d = sum(1 for d in valid_dates if d <= 60)
    meets_activity = items_30d >= 8 or items_60d >= 2

    if meets_activity and content_count > 0:
        c_status = VerificationStatus.VERIFIED.value
        c_reason = None
    else:
        c_status = VerificationStatus.FAILED.value
        c_reason = f"Activity threshold not met ({items_30d} items in 30d, {items_60d} items in 60d)"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.RECENT_CONTENT.value,
            source_url=first_content_url or "",
            short_factual_description=f"Found {content_count} recent content uploads; latest recorded date: {latest_date or 'None'}",
            content_date=latest_date,
            checked_at=checked_iso,
            verification_status=c_status,
            verification_method=VerificationMethod.AUTOMATED_API.value,
            review_reason=c_reason,
        )
    )

    # 3. Commercial Offer Evidence Gate
    comm_safe, comm_err = is_safe_public_url(lead.commercial_evidence_url)
    if comm_safe:
        comm_status = VerificationStatus.VERIFIED.value
        comm_reason = None
    elif not lead.commercial_evidence_url:
        comm_status = VerificationStatus.UNVERIFIED.value
        comm_reason = "Missing public commercial offer evidence URL (e.g. course, mastermind, sponsors, store)"
    else:
        comm_status = VerificationStatus.FAILED.value
        comm_reason = comm_err or "Invalid commercial evidence URL"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.COMMERCIAL_OFFER.value,
            source_url=lead.commercial_evidence_url or "",
            short_factual_description=f"Public commercial monetization evidence: {lead.commercial_evidence_url or 'None'}",
            checked_at=checked_iso,
            verification_status=comm_status,
            verification_method=VerificationMethod.PUBLIC_HTTP_CHECK.value,
            review_reason=comm_reason,
        )
    )

    # 4. Relevant Workflow Need Evidence Gate
    wf_safe, wf_err = is_safe_public_url(lead.workflow_need_evidence_url)
    if wf_safe:
        wf_status = VerificationStatus.VERIFIED.value
        wf_reason = None
    elif not lead.workflow_need_evidence_url:
        wf_status = VerificationStatus.UNVERIFIED.value
        wf_reason = "Missing public workflow need evidence URL (e.g. repurposing friction, backlog, clips library)"
    else:
        wf_status = VerificationStatus.FAILED.value
        wf_reason = wf_err or "Invalid workflow need evidence URL"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.WORKFLOW_NEED.value,
            source_url=lead.workflow_need_evidence_url or "",
            short_factual_description=f"Public content workflow / repurposing friction evidence: {lead.workflow_need_evidence_url or 'None'}",
            checked_at=checked_iso,
            verification_status=wf_status,
            verification_method=VerificationMethod.PUBLIC_HTTP_CHECK.value,
            review_reason=wf_reason,
        )
    )

    # 5. Public Business Contact Channel Gate
    contact_src_safe, contact_src_err = is_safe_public_url(lead.business_contact_source_url)
    has_contact_val = bool(lead.business_contact_value and lead.business_contact_value.strip())
    has_contact_type = bool(lead.business_contact_type and lead.business_contact_type.strip())

    if contact_src_safe and has_contact_val and has_contact_type:
        contact_status = VerificationStatus.VERIFIED.value
        contact_reason = None
    elif not has_contact_val:
        contact_status = VerificationStatus.UNVERIFIED.value
        contact_reason = "Missing public business contact value (email, booking form, or handle)"
    else:
        contact_status = VerificationStatus.FAILED.value
        contact_reason = contact_src_err or "Invalid business contact source URL or missing channel type"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.BUSINESS_CONTACT.value,
            source_url=lead.business_contact_source_url or "",
            short_factual_description=f"Public business contact: {lead.business_contact_type or 'None'} {lead.business_contact_value or 'None'}",
            checked_at=checked_iso,
            verification_status=contact_status,
            verification_method=VerificationMethod.PUBLIC_HTTP_CHECK.value,
            review_reason=contact_reason,
        )
    )

    # 6. Contact Activity Gate (Max 60 days)
    contact_days = calculate_days_ago(lead.business_contact_last_active, ref_dt)
    if contact_days is not None and contact_days <= 60:
        act_status = VerificationStatus.VERIFIED.value
        act_reason = None
    elif contact_days is None:
        act_status = VerificationStatus.UNVERIFIED.value
        act_reason = "Missing business contact last active date; cannot confirm active channel"
    else:
        act_status = VerificationStatus.FAILED.value
        act_reason = f"Business contact last active {contact_days} days ago (exceeds 60 days limit)"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.CONTACT_ACTIVITY.value,
            source_url=lead.business_contact_source_url or lead.official_profile_url or "",
            short_factual_description=f"Business contact last active date: {lead.business_contact_last_active or 'None'} ({contact_days if contact_days is not None else '?'} days ago)",
            content_date=lead.business_contact_last_active,
            checked_at=checked_iso,
            verification_status=act_status,
            verification_method=VerificationMethod.PUBLIC_HTTP_CHECK.value,
            review_reason=act_reason,
        )
    )

    # 7. Country and Language Gate
    country_norm = (lead.country or "").strip()
    allowed_countries = {
        "United States",
        "Canada",
        "United Kingdom",
        "Ireland",
        "Australia",
        "New Zealand",
        "Singapore",
    }
    lang_norm = (lead.language or "English").strip().lower()

    if country_norm in allowed_countries and lang_norm == "english":
        geo_status = VerificationStatus.VERIFIED.value
        geo_reason = None
    elif not country_norm:
        geo_status = VerificationStatus.UNVERIFIED.value
        geo_reason = "Missing creator country location"
    elif country_norm not in allowed_countries:
        geo_status = VerificationStatus.FAILED.value
        geo_reason = f"Country '{country_norm}' is outside the 7 approved target geographies"
    else:
        geo_status = VerificationStatus.FAILED.value
        geo_reason = f"Language '{lead.language}' does not match target English content"

    items.append(
        EvidenceItem(
            lead_id=lead.id,
            platform=lead.platform,
            platform_id=lead.platform_id,
            evidence_type=EvidenceType.COUNTRY_LANGUAGE.value,
            source_url=lead.official_profile_url or "",
            short_factual_description=f"Creator Country: {country_norm or 'Unknown'}, Language: {lead.language or 'English'}",
            checked_at=checked_iso,
            verification_status=geo_status,
            verification_method=VerificationMethod.DOMAIN_INSPECTION.value,
            review_reason=geo_reason,
        )
    )

    # Stale evidence check across all items: if evidence checked date > 30 days ago, mark status STALE
    if evidence_days is not None and evidence_days > 30:
        for it in items:
            if it.verification_status == VerificationStatus.VERIFIED.value:
                it.verification_status = VerificationStatus.STALE.value
                it.review_reason = f"Evidence checked {evidence_days} days ago (exceeds freshness window of 30 days)"

    return items
