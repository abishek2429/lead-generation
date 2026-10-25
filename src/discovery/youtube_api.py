"""
YouTube Data API v3 discovery client.
Uses permitted public Google APIs to discover creator channels and recent uploads.
Complies with terms: no unauthorized scraping, no fabricated data, no guessed emails.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from src.discovery.base import BaseDiscovery
from src.logging_config import get_logger
from src.models import Lead, QualificationStatus

logger = get_logger("youtube_api")

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Map 2-letter ISO country codes commonly returned by YouTube to full country names
COUNTRY_CODE_MAP = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "IE": "Ireland",
    "AU": "Australia",
    "NZ": "New Zealand",
    "SG": "Singapore",
}


class YouTubeAPIError(Exception):
    """Raised when YouTube API requests fail or quota is exceeded."""
    pass


class YouTubeAPIDiscovery(BaseDiscovery):
    """Discovers creator candidates using YouTube Data API v3."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(source_name="YouTube Data API v3")
        self.api_key = api_key

    def is_configured(self) -> bool:
        """Check if an API key is available."""
        return bool(self.api_key and self.api_key.strip())

    def search_channels(
        self,
        query: str,
        max_results: int = 10,
        creator_type: str = "youtube_video_first_creator",
        run_id: Optional[str] = None,
    ) -> List[Lead]:
        """
        Execute YouTube API channel search and fetch uploads.
        Returns newly discovered candidate leads in 'discovered' status.
        """
        if not self.is_configured():
            logger.warning("YouTube API key not configured. Cannot perform live API search.")
            return []

        search_url = f"{YOUTUBE_API_BASE}/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "channel",
            "maxResults": min(max_results, 50),
            "key": self.api_key,
        }

        try:
            resp = requests.get(search_url, params=params, timeout=10)
            if resp.status_code == 403:
                err_data = resp.json().get("error", {})
                msg = err_data.get("message", "Forbidden or Quota Exceeded")
                logger.error(f"YouTube API quota error (403): {msg}")
                raise YouTubeAPIError(f"YouTube API quota exceeded or forbidden: {msg}")
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error(f"YouTube search request failed: {exc}")
            raise YouTubeAPIError(f"HTTP request error: {exc}")

        items = data.get("items", [])
        channel_ids = [item.get("snippet", {}).get("channelId") for item in items if item.get("snippet")]
        channel_ids = [cid for cid in channel_ids if cid]

        if not channel_ids:
            logger.info(f"No channels found for query '{query}'")
            return []

        # Fetch channel details (country, custom URL, uploads playlist)
        channel_details = self._get_channel_details(channel_ids)

        candidates: List[Lead] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in items:
            snippet = item.get("snippet", {})
            cid = snippet.get("channelId")
            if not cid:
                continue

            details = channel_details.get(cid, {})
            title = snippet.get("channelTitle") or details.get("title") or "Unknown Creator"
            custom_url = details.get("customUrl")
            profile_url = f"https://youtube.com/{custom_url}" if custom_url else f"https://youtube.com/channel/{cid}"

            country_code = details.get("country")
            country_name = COUNTRY_CODE_MAP.get(country_code, country_code) if country_code else None

            # Get recent video URLs and dates from uploads playlist
            uploads_pid = details.get("uploads_playlist_id")
            content_urls: List[str] = []
            content_dates: List[str] = []
            if uploads_pid:
                content_urls, content_dates = self._get_recent_uploads(uploads_pid, limit=5)

            lead = Lead(
                creator_name=title,
                creator_type=creator_type,
                country=country_name,
                language="English",
                platform="youtube",
                platform_id=cid,
                official_profile_url=profile_url,
                candidate_source_url=f"https://www.googleapis.com/youtube/v3/search?q={query}",
                recent_content_urls=content_urls,
                recent_content_dates=content_dates,
                # Missing evidence is NOT guessed or fabricated
                commercial_evidence_url=None,
                workflow_need_evidence_url=None,
                business_contact_type=None,
                business_contact_value=None,
                business_contact_source_url=None,
                business_contact_last_active=None,
                evidence_checked_at=None,
                qualification_status=QualificationStatus.DISCOVERED.value,
                disqualification_reasons=[],
                score=0.0,
                priority=None,
                first_discovered_at=now_iso,
                last_checked_at=None,
                last_run_id=run_id,
            )
            candidates.append(lead)

        logger.info(f"Discovered {len(candidates)} YouTube candidates for query '{query}'")
        return candidates

    def _get_channel_details(self, channel_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch snippet, statistics, and uploads playlist details for batch of channel IDs."""
        url = f"{YOUTUBE_API_BASE}/channels"
        params = {
            "part": "snippet,contentDetails",
            "id": ",".join(channel_ids[:50]),
            "key": self.api_key,
        }
        details: Dict[str, Dict[str, Any]] = {}
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    cid = item.get("id")
                    snip = item.get("snippet", {})
                    cdetails = item.get("contentDetails", {})
                    details[cid] = {
                        "title": snip.get("title"),
                        "country": snip.get("country"),
                        "customUrl": snip.get("customUrl"),
                        "uploads_playlist_id": cdetails.get("relatedPlaylists", {}).get("uploads"),
                    }
        except Exception as exc:
            logger.warning(f"Failed to fetch channel details: {exc}")
        return details

    def _get_recent_uploads(self, playlist_id: str, limit: int = 5) -> tuple[List[str], List[str]]:
        """Retrieve recent video URLs and dates from an uploads playlist."""
        url = f"{YOUTUBE_API_BASE}/playlistItems"
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": limit,
            "key": self.api_key,
        }
        urls: List[str] = []
        dates: List[str] = []
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    snip = item.get("snippet", {})
                    res_id = snip.get("resourceId", {})
                    vid_id = res_id.get("videoId")
                    if vid_id:
                        urls.append(f"https://youtube.com/watch?v={vid_id}")
                    pub_at = snip.get("publishedAt")
                    if pub_at:
                        # Extract YYYY-MM-DD
                        dates.append(pub_at[:10])
        except Exception as exc:
            logger.warning(f"Failed to fetch uploads playlist: {exc}")
        return urls, dates

    def discover(self, query: str = "creator podcast", **kwargs: Any) -> List[Lead]:
        """Base discovery implementation."""
        return self.search_channels(query=query, **kwargs)
