"""
Unit tests for URL canonicalization and deterministic lead deduplication.
"""

import pytest
from src.deduplication import canonicalize_url, deduplicate_batch, merge_leads
from src.models import Lead


def test_canonicalize_url_cleanups():
    # Strips trailing slash and www
    assert canonicalize_url("https://www.youtube.com/@techcreator/") == "https://youtube.com/@techcreator"
    # Strips tracking query parameters
    assert (
        canonicalize_url("https://youtube.com/@techcreator?utm_source=twitter&utm_medium=social&si=12345")
        == "https://youtube.com/@techcreator"
    )
    # Adds https scheme if missing
    assert canonicalize_url("youtube.com/@techcreator") == "https://youtube.com/@techcreator"
    # Preserves legitimate non-tracking query parameters sorted
    assert (
        canonicalize_url("https://techcreator.com/courses?category=marketing&level=advanced")
        == "https://techcreator.com/courses?category=marketing&level=advanced"
    )


def test_merge_leads_deterministic():
    older_lead = Lead(
        creator_name="Original Creator",
        creator_type="podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_DEDUP_1",
        official_profile_url="https://youtube.com/@orig",
        candidate_source_url="https://source1.com",
        recent_content_urls=["https://youtube.com/watch?v=111"],
        recent_content_dates=["2026-10-10"],
        commercial_evidence_url=None,  # missing
        workflow_need_evidence_url=None,  # missing
        first_discovered_at="2026-10-01T10:00:00Z",
    )

    incoming_lead = Lead(
        creator_name="Original Creator",
        creator_type="video_podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_DEDUP_1",
        official_profile_url="https://youtube.com/@orig",
        candidate_source_url="https://source2.com",
        recent_content_urls=["https://youtube.com/watch?v=111", "https://youtube.com/watch?v=222"],
        recent_content_dates=["2026-10-15"],
        commercial_evidence_url="https://orig.com/store",  # newly discovered
        workflow_need_evidence_url="https://orig.com/podcast",  # newly discovered
        first_discovered_at="2026-10-20T10:00:00Z",  # later timestamp
        business_contact_type="email",
        business_contact_value="hello@orig.com",
        business_contact_source_url="https://orig.com/contact",
        business_contact_last_active="2026-10-20",
    )

    merged, has_changes = merge_leads(older_lead, incoming_lead, run_id="run_merge_1")

    assert has_changes is True
    # Retains earlier discovery date
    assert merged.first_discovered_at == "2026-10-01T10:00:00Z"
    # Unions content URLs without duplicate
    assert len(merged.recent_content_urls) == 2
    assert "https://youtube.com/watch?v=111" in merged.recent_content_urls
    assert "https://youtube.com/watch?v=222" in merged.recent_content_urls
    # Dates merged
    assert "2026-10-15" in merged.recent_content_dates
    assert "2026-10-10" in merged.recent_content_dates
    # Fills missing evidence
    assert merged.commercial_evidence_url == "https://orig.com/store"
    assert merged.workflow_need_evidence_url == "https://orig.com/podcast"
    assert merged.business_contact_value == "hello@orig.com"
    assert merged.last_run_id == "run_merge_1"


def test_deduplicate_batch_by_platform_and_canonical_url():
    existing_1 = Lead(
        creator_name="Channel One",
        creator_type="podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_EXISTING_1",
        official_profile_url="https://youtube.com/@chan1",
        candidate_source_url="https://src.com",
        recent_content_urls=["https://youtube.com/watch?v=1"],
    )

    # Incoming with same platform_id
    incoming_same_pid = Lead(
        creator_name="Channel One Updated",
        creator_type="video_podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_EXISTING_1",
        official_profile_url="https://youtube.com/@chan1",
        candidate_source_url="https://src2.com",
        recent_content_urls=["https://youtube.com/watch?v=1", "https://youtube.com/watch?v=2"],
    )

    # Incoming with different platform_id but same canonical profile URL
    incoming_same_url = Lead(
        creator_name="Channel One Alternate ID",
        creator_type="podcaster",
        country="United States",
        platform="youtube",
        platform_id="UC_DIFFERENT_RAW_ID",
        official_profile_url="https://www.youtube.com/@chan1/",  # will canonicalize to match
        candidate_source_url="https://src3.com",
        commercial_evidence_url="https://chan1.com/store",
    )

    # Incoming brand new
    incoming_brand_new = Lead(
        creator_name="Brand New Channel",
        creator_type="educator_creator",
        country="Canada",
        platform="youtube",
        platform_id="UC_BRAND_NEW",
        official_profile_url="https://youtube.com/@newchannel",
        candidate_source_url="https://src4.com",
    )

    to_insert, to_update, stats = deduplicate_batch(
        existing_leads=[existing_1],
        incoming_candidates=[incoming_same_pid, incoming_same_url, incoming_brand_new],
        run_id="run_batch_dedup",
    )

    assert stats["total_incoming"] == 3
    assert stats["new_records"] == 1
    assert len(to_insert) == 1
    assert to_insert[0].platform_id == "UC_BRAND_NEW"
    assert len(to_update) == 1
    assert to_update[0].platform_id == "UC_EXISTING_1"
    # Merged has new content url and commercial evidence
    assert len(to_update[0].recent_content_urls) == 2
    assert to_update[0].commercial_evidence_url == "https://chan1.com/store"
