from typing import Any, Dict, List, Optional

import requests


class TavilyClient:
    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout
        self.base = "https://api.tavily.com"

    def search(
        self,
        query: str,
        max_results: int = 8,
        search_depth: str = "advanced",
        include_raw_content: bool = False,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        r = requests.post(f"{self.base}/search", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def extract(
        self,
        url: str,
        include_images: bool = False,
        extract_depth: str = "advanced",
    ) -> Dict[str, Any]:
        payload = {
            "api_key": self.api_key,
            "urls": [url],
            "include_images": include_images,
            "extract_depth": extract_depth,
        }
        r = requests.post(f"{self.base}/extract", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
