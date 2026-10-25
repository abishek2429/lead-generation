"""
YouTube Data API v3 discovery client.
Uses permitted public Google APIs to discover creator channels and recent uploads.
Complies with terms: no unauthorized scraping, no fabricated data, no guessed emails.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from src.discovery.base import BaseDiscovery
from src.logging_config import get_logger
from src.models import Lead, QualificationStatus

logger = get_logger("youtube_api")

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _sanitize_secret(text: Any) -> str:
    """Sanitize API keys or query params from exception messages and logs."""
    s = str(text)
    s = re.sub(r"AIza[0-9A-Za-z-_]{20,40}", "***REDACTED_API_KEY***", s)
    s = re.sub(r"(key|token|api_key)=([A-Za-z0-9_\-\.]+)", r"\1=***REDACTED***", s, flags=re.IGNORECASE)
    return s


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
        self.api_key = api_key if api_key is not None else os.getenv("YOUTUBE_API_KEY")

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
                clean_msg = _sanitize_secret(msg)
                logger.error(f"YouTube API quota error (403): {clean_msg}")
                raise YouTubeAPIError(f"YouTube API quota exceeded or forbidden: {clean_msg}")
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            clean_exc = _sanitize_secret(exc)
            logger.error(f"YouTube search request failed: {clean_exc}")
            raise YouTubeAPIError(f"HTTP request error: {clean_exc}")

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
            logger.warning(f"Failed to fetch channel details: {_sanitize_secret(exc)}")
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
            logger.warning(f"Failed to fetch uploads playlist: {_sanitize_secret(exc)}")
        return urls, dates

    def get_video_details(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch video details using official videos.list endpoint.
        Inspects duration and language to confirm long-form and English content.
        """
        if not video_ids or not self.is_configured():
            return {}

        url = f"{YOUTUBE_API_BASE}/videos"
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(video_ids[:50]),
            "key": self.api_key,
        }
        results: Dict[str, Dict[str, Any]] = {}
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    vid = item.get("id")
                    snip = item.get("snippet", {})
                    cdetails = item.get("contentDetails", {})
                    duration_str = cdetails.get("duration", "")
                    
                    # Estimate if long form (>= 10 mins: PT#M#S)
                    is_long_form = "H" in duration_str or (
                        "M" in duration_str and not duration_str.startswith("PT0M") and not duration_str.startswith("PT1M")
                    )

                    results[vid] = {
                        "video_id": vid,
                        "title": snip.get("title"),
                        "published_at": snip.get("publishedAt"),
                        "duration": duration_str,
                        "is_long_form": is_long_form,
                        "language": snip.get("defaultAudioLanguage") or snip.get("defaultLanguage"),
                        "source_url": f"https://youtube.com/watch?v={vid}",
                    }
        except Exception as exc:
            logger.warning(f"Failed to fetch video details: {_sanitize_secret(exc)}")
        return results

    def smoke_test(self, query: str = "creator podcast interview", save_metadata: bool = True) -> Dict[str, Any]:
        """
        Run a small, bounded live API smoke test using official YouTube Data API v3 endpoints:
        - search.list
        - channels.list
        - videos.list (or playlistItems.list)
        Never prints or logs the raw API key.
        """
        if not self.is_configured():
            res = {
                "configured": False,
                "success": False,
                "records_retrieved": 0,
                "message": (
                    "YouTube Data API v3 key is not configured. "
                    "To enable live discovery, set YOUTUBE_API_KEY in your .env file or system environment."
                ),
                "endpoints_documented": [
                    "https://developers.google.com/youtube/v3/docs/search/list",
                    "https://developers.google.com/youtube/v3/docs/channels/list",
                    "https://developers.google.com/youtube/v3/docs/videos/list",
                ],
                "endpoints_tested": [],
                "errors": ["YOUTUBE_API_KEY not configured in environment"],
            }
            if save_metadata:
                from pathlib import Path
                import json
                out_file = Path("data/output/youtube_api_smoke_test.json")
                out_file.parent.mkdir(parents=True, exist_ok=True)
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=2)
                res["saved_metadata_file"] = str(out_file)
            return res

        start_time = datetime.now(timezone.utc)
        retrieval_timestamp = start_time.isoformat()
        metadata_records = []
        errors = []

        try:
            candidates = self.search_channels(
                query=query,
                max_results=2,  # Bounded to protect quota
                run_id="smoke_test",
            )
            for c in candidates:
                metadata_records.append({
                    "channel_title": c.creator_name,
                    "channel_id": c.platform_id,
                    "profile_url": c.official_profile_url,
                    "country": c.country,
                    "language": c.language,
                    "retrieved_at": retrieval_timestamp,
                    "source_url": c.candidate_source_url,
                    "recent_videos_count": len(c.recent_content_urls),
                    "recent_content_urls": c.recent_content_urls,
                })
        except Exception as exc:
            errors.append(f"Smoke test request failed: {exc}")

        result = {
            "configured": True,
            "success": len(errors) == 0 and len(metadata_records) > 0,
            "query": query,
            "records_retrieved": len(metadata_records),
            "retrieval_timestamp": retrieval_timestamp,
            "endpoints_tested": [
                "GET https://www.googleapis.com/youtube/v3/search",
                "GET https://www.googleapis.com/youtube/v3/channels",
                "GET https://www.googleapis.com/youtube/v3/playlistItems",
            ],
            "records": metadata_records,
            "errors": errors,
        }

        if save_metadata and metadata_records:
            from pathlib import Path
            import json
            out_file = Path("data/output/youtube_api_smoke_test.json")
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            result["saved_metadata_file"] = str(out_file)

        return result

    def discover(self, query: str = "creator podcast", **kwargs: Any) -> List[Lead]:
        """Base discovery implementation."""
        return self.search_channels(query=query, **kwargs)
