import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

import requests

from . import __version__

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"
DEFAULT_USER_AGENT = f"HiDair-Feather/{__version__} (+https://example.invalid)"

try:
    from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    from youtube_transcript_api import _errors as yt_errors  # type: ignore
    from youtube_transcript_api.proxies import GenericProxyConfig  # type: ignore
except Exception:
    YouTubeTranscriptApi = None
    yt_errors = None
    GenericProxyConfig = None

TRANSCRIPT_AVAILABLE = YouTubeTranscriptApi is not None


def request_headers() -> Dict[str, str]:
    ua = os.getenv("HIDAIR_USER_AGENT", DEFAULT_USER_AGENT)
    return {"User-Agent": ua, "Accept": "application/json"}


def isoformat_utc(dt_val: dt.datetime) -> str:
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=dt.timezone.utc)
    return dt_val.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunked(items: List[str], size: int = 50) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if "youtu.be" in host:
        vid = path.lstrip("/").split("/", 1)[0]
        return vid or None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        if path == "/watch":
            qs = parse_qs(parsed.query)
            return (qs.get("v") or [None])[0]
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if path.startswith(prefix):
                vid = path[len(prefix) :].split("/", 1)[0]
                return vid or None
    return None


def detail_to_metadata(item: Dict[str, Any], rank: Optional[int] = None, source: Optional[str] = None) -> Dict[str, Any]:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    content = item.get("contentDetails") or {}
    video_id = item.get("id")
    payload: Dict[str, Any] = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel_title": snippet.get("channelTitle"),
        "channel_id": snippet.get("channelId"),
        "published_at": snippet.get("publishedAt"),
        "duration": content.get("duration"),
        "tags": snippet.get("tags") or [],
        "view_count": stats.get("viewCount"),
        "like_count": stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
    }
    if rank is not None:
        payload["search_rank"] = rank
    if source:
        payload["source"] = source
    return payload


def snippet_to_metadata(
    video_id: str,
    snippet: Dict[str, Any],
    rank: Optional[int] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel_title": snippet.get("channelTitle"),
        "channel_id": snippet.get("channelId"),
        "published_at": snippet.get("publishedAt"),
    }
    if rank is not None:
        payload["search_rank"] = rank
    if source:
        payload["source"] = source
    return payload


def parse_api_error(response: Optional[requests.Response]) -> tuple[Optional[str], Optional[str]]:
    if response is None:
        return None, None
    try:
        data = response.json()
    except Exception:
        return None, None
    err = data.get("error") or {}
    message = err.get("message")
    errors = err.get("errors") or []
    reason = None
    if isinstance(errors, list) and errors:
        reason = errors[0].get("reason")
    return reason, message


def youtube_search(
    query: str,
    api_key: str,
    max_results: int,
    order: str = "relevance",
    published_after: Optional[dt.datetime] = None,
    published_before: Optional[dt.datetime] = None,
    relevance_language: Optional[str] = None,
    details_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    fetch_details: bool = True,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    remaining = max_results

    while remaining > 0:
        params: Dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": min(50, remaining),
            "order": order,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        if published_after:
            params["publishedAfter"] = isoformat_utc(published_after)
        if published_before:
            params["publishedBefore"] = isoformat_utc(published_before)
        if relevance_language:
            params["relevanceLanguage"] = relevance_language

        r = requests.get(f"{YOUTUBE_BASE}/search", params=params, timeout=60, headers=request_headers())
        r.raise_for_status()
        data = r.json()
        batch = data.get("items", []) or []
        items.extend(batch)
        remaining = max_results - len(items)
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    video_ids = []
    snippets: Dict[str, Dict[str, Any]] = {}
    for item in items:
        vid = (item.get("id") or {}).get("videoId")
        if vid:
            video_ids.append(vid)
            snippets[vid] = item.get("snippet") or {}

    details: Dict[str, Dict[str, Any]] = {}
    if fetch_details and video_ids:
        need_ids = video_ids
        if details_cache is not None:
            need_ids = [vid for vid in video_ids if vid not in details_cache]
        if need_ids:
            details = fetch_video_details(need_ids, api_key)
            if details_cache is not None:
                details_cache.update(details)
    results: List[Dict[str, Any]] = []
    for idx, vid in enumerate(video_ids, start=1):
        info = None
        if details_cache is not None:
            info = details_cache.get(vid)
        if info is None:
            info = details.get(vid)
        if info:
            results.append(detail_to_metadata(info, rank=idx, source="search"))
        else:
            results.append(snippet_to_metadata(vid, snippets.get(vid, {}), rank=idx, source="search"))
        if len(results) >= max_results:
            break
    return results


def fetch_video_details(video_ids: List[str], api_key: str) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    for chunk in chunked(video_ids, 50):
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(chunk),
            "key": api_key,
            "maxResults": len(chunk),
        }
        r = requests.get(f"{YOUTUBE_BASE}/videos", params=params, timeout=60, headers=request_headers())
        r.raise_for_status()
        data = r.json()
        for item in data.get("items", []) or []:
            vid = item.get("id")
            if vid:
                details[vid] = item
    return details


def fetch_transcript(video_id: str, languages: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if not TRANSCRIPT_AVAILABLE:
        raise RuntimeError("Missing dependency: youtube-transcript-api (pip install youtube-transcript-api)")
    lang_list = [lang for lang in (languages or []) if lang]
    if not lang_list:
        lang_list = ["en"]
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        return YouTubeTranscriptApi.get_transcript(video_id, languages=lang_list)
    api = build_transcript_api()
    if hasattr(api, "fetch"):
        return api.fetch(video_id, languages=lang_list)  # type: ignore[return-value]
    if hasattr(api, "list"):
        if not lang_list:
            lang_list = ["en"]
        transcript = api.list(video_id).find_transcript(lang_list)
        return transcript.fetch()  # type: ignore[return-value]
    raise RuntimeError("Unsupported youtube-transcript-api version: missing fetch/list/get_transcript")


def build_transcript_api() -> Any:
    if not TRANSCRIPT_AVAILABLE:
        raise RuntimeError("Missing dependency: youtube-transcript-api (pip install youtube-transcript-api)")
    proxy_http = os.getenv("YOUTUBE_PROXY_HTTP")
    proxy_https = os.getenv("YOUTUBE_PROXY_HTTPS")
    proxy = os.getenv("YOUTUBE_PROXY")
    if proxy and not proxy_http and not proxy_https:
        proxy_http = proxy
        proxy_https = proxy
    proxy_config = None
    if (proxy_http or proxy_https) and GenericProxyConfig is not None:
        proxy_config = GenericProxyConfig(http_url=proxy_http, https_url=proxy_https)
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def classify_transcript_error(exc: Exception) -> str:
    if yt_errors is None:
        return "error"
    blocked = (yt_errors.IpBlocked, yt_errors.RequestBlocked, yt_errors.YouTubeRequestFailed)
    unavailable = (
        yt_errors.TranscriptsDisabled,
        yt_errors.NoTranscriptFound,
        yt_errors.VideoUnavailable,
        yt_errors.VideoUnplayable,
        yt_errors.AgeRestricted,
        yt_errors.CouldNotRetrieveTranscript,
        yt_errors.YouTubeDataUnparsable,
    )
    if isinstance(exc, blocked):
        return "blocked"
    if isinstance(exc, unavailable):
        return "unavailable"
    return "error"


def format_transcript(segments: Iterable[Any]) -> str:
    lines: List[str] = []
    for seg in segments:
        if isinstance(seg, dict):
            start = float(seg.get("start") or 0)
            text = str(seg.get("text") or "")
        else:
            start = float(getattr(seg, "start", 0) or 0)
            text = str(getattr(seg, "text", "") or "")
        minutes = int(start // 60)
        seconds = int(start % 60)
        stamp = f"{minutes:02d}:{seconds:02d}"
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        lines.append(f"[{stamp}] {text}")
    return "\n".join(lines)
