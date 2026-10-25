"""
Unit tests for CSV Import discovery module.
Ensures candidate discovery handles varied headers and sets qualification_status='discovered'.
"""

import io
import pytest
from src.discovery.import_csv import CSVDiscovery
from src.models import QualificationStatus


def test_csv_import_standard_headers():
    csv_content = """creator_name,creator_type,country,platform,platform_id,official_profile_url,candidate_source_url,recent_content_urls,recent_content_dates
The SaaS Podcast,podcaster,United States,youtube,UC_SAAS,https://youtube.com/@saaspodcast,https://youtube.com,https://youtube.com/watch?v=1,2026-10-20
Code & Coffee,educator_creator,Canada,youtube,UC_COFFEE,https://youtube.com/@codecof,https://google.com,https://youtube.com/watch?v=2,2026-10-18
"""
    importer = CSVDiscovery()
    leads, errors = importer.parse_csv(io.StringIO(csv_content), run_id="run_csv_test")

    assert len(errors) == 0
    assert len(leads) == 2

    # Status must default to discovered
    assert leads[0].qualification_status == QualificationStatus.DISCOVERED.value
    assert leads[0].creator_name == "The SaaS Podcast"
    assert leads[0].platform_id == "UC_SAAS"
    assert leads[0].last_run_id == "run_csv_test"

    assert leads[1].creator_name == "Code & Coffee"
    assert leads[1].country == "Canada"
    assert leads[1].recent_content_urls == ["https://youtube.com/watch?v=2"]


def test_csv_import_flexible_aliases():
    csv_content = """Name,Segment,Location,Source Platform,Channel ID,Channel URL,Source URL
Alex Rivera,video_podcaster,United Kingdom,youtube,UC_ALEX,https://youtube.com/@alexrivera,https://search.com
"""
    importer = CSVDiscovery()
    leads, errors = importer.parse_csv(io.StringIO(csv_content))

    assert len(errors) == 0
    assert len(leads) == 1
    assert leads[0].creator_name == "Alex Rivera"
    assert leads[0].creator_type == "video_podcaster"
    assert leads[0].country == "United Kingdom"
    assert leads[0].platform_id == "UC_ALEX"
    assert leads[0].official_profile_url == "https://youtube.com/@alexrivera"


def test_csv_import_missing_mandatory_columns():
    # Missing platform and platform_id
    csv_content = """creator_name,country
Random Creator,United States
"""
    importer = CSVDiscovery()
    leads, errors = importer.parse_csv(io.StringIO(csv_content))

    assert len(leads) == 0
    assert len(errors) == 1
    assert "missing mandatory columns" in errors[0]
