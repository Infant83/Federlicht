import html
import os
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

from . import __version__

DEFAULT_USER_AGENT = f"Feather/{__version__} (+https://example.invalid)"
ACTIVITY_PATTERNS = (
    re.compile(r"urn:li:activity:(\d+)", re.IGNORECASE),
    re.compile(r"activity-(\d+)", re.IGNORECASE),
    re.compile(r"activity/(\d+)", re.IGNORECASE),
)


def request_headers() -> Dict[str, str]:
    ua = os.getenv("FEATHER_USER_AGENT", DEFAULT_USER_AGENT)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def extract_activity_id(url: str) -> Optional[str]:
    for pattern in ACTIVITY_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def build_embed_url(activity_id: str) -> str:
    return f"https://www.linkedin.com/embed/feed/update/urn:li:activity:{activity_id}"


def fetch_embed_html(embed_url: str, timeout: int = 30) -> str:
    resp = requests.get(embed_url, timeout=timeout, headers=request_headers())
    resp.raise_for_status()
    return resp.text


def extract_meta(html_text: str, key: str, prop: bool = False) -> Optional[str]:
    attr = "property" if prop else "name"
    pattern = rf'<meta[^>]+{attr}="{re.escape(key)}"[^>]+content="([^"]+)"'
    m = re.search(pattern, html_text, re.IGNORECASE)
    if not m:
        return None
    return html.unescape(m.group(1)).strip()


def extract_title(html_text: str) -> Optional[str]:
    m = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return html.unescape(m.group(1)).strip()


def unwrap_linkedin_redirect(url: str) -> str:
    parsed = urlparse(url)
    if "linkedin.com" in parsed.netloc and parsed.path.startswith("/redir/redirect"):
        params = parse_qs(parsed.query)
        target = params.get("url")
        if target:
            return unquote(target[0])
    return url


def extract_commentary_html(html_text: str) -> Optional[str]:
    pattern = r'data-test-id="main-feed-activity-embed-card__commentary"[^>]*>(.*?)</p>'
    m = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1)


def html_to_text(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    def replace_link(match: re.Match) -> str:
        url = html.unescape(match.group(1))
        return unwrap_linkedin_redirect(url)

    text = re.sub(
        r"<a[^>]+href=\"([^\"]+)\"[^>]*>.*?</a>",
        replace_link,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_links(commentary_html: Optional[str]) -> List[str]:
    if not commentary_html:
        return []
    links = []
    for href in re.findall(r'href="([^"]+)"', commentary_html, re.IGNORECASE):
        url = html.unescape(href)
        url = unwrap_linkedin_redirect(url)
        if url not in links:
            links.append(url)
    return links


def extract_images(html_text: str) -> List[str]:
    images: List[str] = []
    for url in re.findall(r'data-delayed-url="([^"]+)"', html_text, re.IGNORECASE):
        img = html.unescape(url)
        if img not in images:
            images.append(img)
    og_image = extract_meta(html_text, "og:image", prop=True)
    if og_image and og_image not in images:
        images.insert(0, og_image)
    return images


def extract_public_post(url: str, timeout: int = 30) -> Optional[Dict[str, object]]:
    activity_id = extract_activity_id(url)
    if not activity_id:
        return None
    embed_url = build_embed_url(activity_id)
    html_text = fetch_embed_html(embed_url, timeout=timeout)
    commentary_html = extract_commentary_html(html_text)
    content_text = html_to_text(commentary_html or "")

    title = extract_meta(html_text, "og:title", prop=True) or extract_title(html_text) or "LinkedIn Post"
    description = extract_meta(html_text, "description") or extract_meta(html_text, "og:description", prop=True)
    if not content_text and description:
        content_text = description

    links = extract_links(commentary_html)
    images = extract_images(html_text)

    if not content_text and not images:
        return None

    return {
        "results": [
            {
                "url": url,
                "title": title,
                "raw_content": content_text,
                "description": description,
                "links": links,
                "images": images,
                "embed_url": embed_url,
                "activity_id": activity_id,
                "extractor": "linkedin_embed",
            }
        ],
        "failed_results": [],
        "response_time": 0.0,
        "request_id": "local-linkedin-embed",
    }
