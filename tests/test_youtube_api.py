"""
Unit and integration tests for YouTube Data API v3 discovery client.
Tests bounded discovery, error handling, quota exhaustion, metadata persistence,
and verifies that YouTube discovery does NOT fabricate evidence or false qualifications.
"""

from unittest.mock import MagicMock, patch
import json
import pytest
import requests

from src.discovery.youtube_api import YouTubeAPIDiscovery, YouTubeAPIError
from src.models import QualificationStatus


def test_youtube_api_unconfigured_behavior():
    """Verify that absent API key behaves gracefully without fabricating success."""
    client = YouTubeAPIDiscovery(api_key=None)
    assert not client.is_configured()

    results = client.search_channels("podcast")
    assert results == []

    smoke = client.smoke_test(save_metadata=False)
    assert not smoke["configured"]
    assert not smoke["success"]
    assert smoke["records_retrieved"] == 0
    assert "YOUTUBE_API_KEY" in smoke["message"]
    assert len(smoke["errors"]) > 0


def test_youtube_api_mocked_discovery_success():
    """Verify discovery flow parses channels, details, and uploads correctly."""
    client = YouTubeAPIDiscovery(api_key="AIzaSyMockKeyForTesting123456789")
    assert client.is_configured()

    search_response = {
        "items": [
            {
                "snippet": {
                    "channelId": "UC1234567890abcdef",
                    "channelTitle": "SaaS Leaders Show",
                }
            }
        ]
    }

    channels_response = {
        "items": [
            {
                "id": "UC1234567890abcdef",
                "snippet": {
                    "title": "SaaS Leaders Show",
                    "country": "US",
                    "customUrl": "@saasleaders",
                },
                "contentDetails": {
                    "relatedPlaylists": {"uploads": "UU1234567890abcdef"}
                },
            }
        ]
    }

    playlist_response = {
        "items": [
            {
                "snippet": {
                    "resourceId": {"videoId": "vid_abc123"},
                    "publishedAt": "2026-10-15T12:00:00Z",
                }
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "vid_def456"},
                    "publishedAt": "2026-10-10T12:00:00Z",
                }
            },
        ]
    }

    def mock_requests_get(url, params=None, timeout=10):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if "search" in url:
            mock_resp.json.return_value = search_response
        elif "channels" in url:
            mock_resp.json.return_value = channels_response
        elif "playlistItems" in url:
            mock_resp.json.return_value = playlist_response
        else:
            mock_resp.json.return_value = {}
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        leads = client.search_channels(query="saas podcast", max_results=5)

    assert len(leads) == 1
    lead = leads[0]
    assert lead.creator_name == "SaaS Leaders Show"
    assert lead.platform == "youtube"
    assert lead.platform_id == "UC1234567890abcdef"
    assert lead.official_profile_url == "https://youtube.com/@saasleaders"
    assert lead.country == "United States"
    assert lead.language == "English"
    assert len(lead.recent_content_urls) == 2
    assert "https://youtube.com/watch?v=vid_abc123" in lead.recent_content_urls
    assert lead.recent_content_dates == ["2026-10-15", "2026-10-10"]

    # CRITICAL: Prevent false qualification.
    # API search alone does NOT fabricate commercial or contact evidence!
    assert lead.qualification_status == QualificationStatus.DISCOVERED.value
    assert lead.commercial_evidence_url is None
    assert lead.workflow_need_evidence_url is None
    assert lead.business_contact_value is None
    assert lead.business_contact_type is None
    assert lead.business_contact_source_url is None


def test_youtube_api_quota_exhaustion_handling():
    """Verify HTTP 403 quota exhaustion triggers YouTubeAPIError and protects secret key."""
    client = YouTubeAPIDiscovery(api_key="AIzaSySecretApiKeyDoNotLeak999")

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {
        "error": {
            "code": 403,
            "message": "The request cannot be completed because you have exceeded your quota.",
            "errors": [{"reason": "quotaExceeded"}],
        }
    }

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(YouTubeAPIError) as exc_info:
            client.search_channels(query="podcast")

        err_msg = str(exc_info.value)
        assert "quota exceeded" in err_msg.lower()
        # Verify API key is NOT leaked in exception or logs
        assert "AIzaSySecretApiKeyDoNotLeak999" not in err_msg


def test_youtube_api_network_timeout():
    """Verify connection timeout is caught and converted cleanly."""
    client = YouTubeAPIDiscovery(api_key="AIzaSyMockKeyForTesting123456789")

    with patch("requests.get", side_effect=requests.Timeout("Connection timed out")):
        with pytest.raises(YouTubeAPIError) as exc_info:
            client.search_channels(query="podcast")

        assert "HTTP request error" in str(exc_info.value)


def test_youtube_api_videos_list_long_form_inspection():
    """Verify videos.list endpoint parses duration and language."""
    client = YouTubeAPIDiscovery(api_key="AIzaSyMockKeyForTesting123456789")

    videos_response = {
        "items": [
            {
                "id": "vid_long123",
                "snippet": {
                    "title": "Deep Dive Ep 42",
                    "publishedAt": "2026-10-20T10:00:00Z",
                    "defaultLanguage": "en",
                },
                "contentDetails": {
                    "duration": "PT45M30S",  # 45 mins -> long form
                },
            },
            {
                "id": "vid_short456",
                "snippet": {
                    "title": "Quick Tip Short",
                    "publishedAt": "2026-10-22T10:00:00Z",
                    "defaultLanguage": "en",
                },
                "contentDetails": {
                    "duration": "PT45S",  # 45 seconds -> short form
                },
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = videos_response

    with patch("requests.get", return_value=mock_resp):
        details = client.get_video_details(["vid_long123", "vid_short456"])

    assert len(details) == 2
    assert details["vid_long123"]["is_long_form"] is True
    assert details["vid_short456"]["is_long_form"] is False
    assert details["vid_long123"]["language"] == "en"
